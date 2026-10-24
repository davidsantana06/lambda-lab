**Lambda Lab** é um sistema especialista em formato de chatbot que gera algoritmos executáveis sob demanda. A partir da descrição de um problema, ele escolhe uma estratégia, escreve o código, valida a sintaxe, executa com os parâmetros do usuário, mede tempo e memória, analisa a complexidade e corrige o código quando ele falha ou é ineficiente.

## 🧩 Módulos

São três módulos, listados na ordem em que devem subir. O serviço cria a rede usada pelo servidor MCP, e o cliente depende do servidor MCP.

### ⚙️ `lambda-lab-service/`

Servidor FastAPI com SQLite, para lidar com algoritmos e execuções que, por sua vez, são persistidos em `/data/service.db` (volume `lambda-lab-service_sqlitedata`). Cada execução roda em segundo plano, num processo Python separado. Sua documentação interativa fica em http://localhost:9000/docs.

| Arquivo          | Responsabilidade                                    |
| ---------------- | --------------------------------------------------- |
| `__main__.py`    | Monta o app, cria as tabelas e sobe o uvicorn       |
| `database.py`    | Engine e sessão, obtidas a partir de `DATABASE_URL` |
| `schemas.py`     | Modelos para entrada e saída de dados               |
| `models.py`      | Tabelas `algorithm` e `execution`                   |
| `services.py`    | Validação, execução isolada e monitoramento         |
| `controllers.py` | Rotas HTTP                                          |

A coluna "Ferramenta MCP" indica a ferramenta correspondente no `lambda-lab-mcp-server/`.

| Rota                                         | Ferramenta MCP                   | Descrição                                                                                                                                            |
| -------------------------------------------- | -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /health`                                | `check_algorithm_service_health` | Estado do serviço                                                                                                                                    |
| `POST /algorithms/validate`                  | `validate_algorithm`             | Valida algoritmos sem salvá-los; em caso de erro, devolve linha, coluna e mensagem                                                                   |
| `POST /algorithms`                           | `create_algorithm`               | Valida e salva algoritmos (`201`) ou devolve `400` em caso de erro                                                                                   |
| `GET /algorithms`                            | `list_algorithms`                | Lista paginada de algoritmos (`limit` 50 e `offset` 0, por padrão)                                                                                   |
| `GET /algorithms/search`                     | `search_algorithms`              | Busca parcial de algoritmos por `name` e `description`, case-insensitive                                                                             |
| `GET /algorithms/{algorithm_id}`             | `get_algorithm`                  | Busca de algoritmo por ID, ou `404`                                                                                                                  |
| `POST /algorithms/{algorithm_id}/executions` | `execute_algorithm`              | Inicia a execução do algoritmo com os `arguments` e devolve `202` com status `pending`                                                               |
| `GET /executions`                            | `list_executions`                | Lista paginada de execuções                                                                                                                          |
| `GET /executions/search`                     | `search_executions`              | Filtra execuções por `status` e `algorithm_id`                                                                                                       |
| `GET /executions/{execution_id}`             | `get_execution`                  | Resumo da execução de algoritmo, com status, resultado, `stdout`, erro (se houver), duração e pico de memória (e `elapsed_in_ms` durante a execução) |

O código precisa definir a função de entrada (`solve`, por padrão) no nível do módulo, e ela é chamada como `solve(**arguments)`. A validação usa `ast.parse` e compila a árvore, então também pega erros como `return` fora de função.

Cada execução roda como `nobody`, numa pasta temporária e com ambiente mínimo, com limite de 10 s e 256 MB de memória. Estes são os principais campos de uma execução:

| Campo                       | Conteúdo                                                                                                                     |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `algorithm_id`              | Algoritmo executado                                                                                                          |
| `arguments`                 | Argumentos nomeados passados à função                                                                                        |
| `status`                    | Começa em `pending`, passa a `running` e termina em `completed`, `failed` ou `timed_out`                                     |
| `result`                    | Valor devolvido pela função, quando `completed`. O que não é JSON é guardado com `repr`                                      |
| `stdout`                    | O que o código imprimiu, separado do resultado e cortado em 10.000 caracteres                                                |
| `error`                     | Traceback do erro, quando `failed`, ou aviso de tempo esgotado, quando `timed_out`                                           |
| `duration_in_ms`            | Tempo só da chamada da função. Em `timed_out`, o tempo total até o processo ser interrompido                                 |
| `peak_memory_in_kb`         | Pico de memória do processo filho, medido com `getrusage`. Inclui cerca de 9 MB do interpretador e fica vazio em `timed_out` |
| `started_at`, `finished_at` | Início e fim da execução                                                                                                     |

---

### 🔌 `lambda-lab-mcp-server/`

Servidor FastMCP com transporte `streamable-http`. Cada ferramenta (ver tabela acima) vira uma requisição HTTP. O `execute_algorithm` espera até 5 segundos pelo fim da execução. Se ela não finalizar durante esse tempo, deve ser acompanhada com `get_execution`.

| Arquivo       | Responsabilidade                                                   |
| ------------- | ------------------------------------------------------------------ |
| `__main__.py` | Registra as ferramentas e sobe o transporte HTTP                   |
| `client.py`   | Chama o serviço com httpx e converte falhas em `ToolError`         |
| `models.py`   | Modelos de dados Pydantic dos recursos devolvidos                  |
| `tools.py`    | Ferramentas, cujas docstrings servem de documentação para o agente |

---

### 💬 `lambda-lab-client/`

Chat Chainlit responsável por acionar modelos de linguagem (Gemini) e tools (descritas acima). Conta com cache semântico local para perguntas repetidas, desde que não acionem tools, além de um juiz LLM que avalia a corretude, eficiência e clareza das respostas. O Chainlit roda em http://localhost:9002.

| Arquivo                     | Responsabilidade                                                 |
| --------------------------- | ---------------------------------------------------------------- |
| `__main__.py`               | Sobe o Chainlit em `0.0.0.0:9002`                                |
| `controllers.py`            | Handlers do Chainlit, que exibem cada chamada de ferramenta      |
| `services/agent_service.py` | Motor de inferência: prompt de sistema e ligação LLM–ferramentas |
| `services/llm_service.py`   | Chat com o Gemini                                                |
| `services/cache_service.py` | Embeddings locais e coleção do cache semântico no ChromaDB       |
| `services/tools_service.py` | Cliente MCP                                                      |
| `services/judge_service.py` | Prompt do juiz e leitura das notas                               |
| `judge.py`                  | Script de avaliação LLM-as-a-Judge                               |
| `chainlit.md`               | Tela de apresentação do chat                                     |

Na raiz de `lambda-lab-client/`, ao lado do `docker-compose.yml`, ficam os 18 casos de avaliação (`judge_cases.json`) e o relatório do juiz (`judge_report.json`).

O prompt de sistema orienta o agente a entender o problema e justificar a estratégia. Em seguida, ele escreve e valida a função de entrada, executando-a (com um exemplo pequeno, se o usuário não der parâmetros). Por fim, relata resultado, tempo, memória e complexidade e corrige o código em até 3 tentativas. Perguntas conceituais são respondidas sem ferramentas. O laço entre LLM e ferramentas tem no máximo 26 passos, e as chamadas usam `reasoning_effort` (`low`, por padrão).

O cache semântico gera o embedding da pergunta localmente, com o modelo multilíngue `paraphrase-multilingual-MiniLM-L12-v2` do sentence-transformers, sem chamar o Gemini. Uma coleção do ChromaDB guarda pergunta, embedding e resposta e devolve a distância de cosseno, convertida em similaridade (1 − distância). A partir do limiar (0,90, por padrão), a resposta vem do cache, e o chat mostra a similaridade. Só a primeira mensagem de cada chat é consultada, e só respostas dadas sem tools são guardadas.

## 🛠️ Instalação e execução

### 1️⃣ Pré-requisitos

Sistema operacional Linux, macOS ou Windows com WSL, além de Docker com o plugin Compose e uma chave da API do Gemini. Não é preciso ter Python no host.

A imagem do cliente ocupa cerca de 3,5 GB, por causa do PyTorch (CPU-only) e do modelo de embeddings. Reserve pelo menos 5 GB livres em disco para as três imagens.

As portas 9000, 9001 e 9002 precisam estar livres. Se alguma estiver ocupada, o compose falha na subida.

### 2️⃣ Subir serviço

```bash
cd lambda-lab-service
docker compose up -d --build
cd ..
```

O comando cria a rede `lambda-lab-network` e o volume `lambda-lab-service_sqlitedata`. Para validar se o serviço está rodando, consulte o `/health`:

```bash
curl http://localhost:9000/health
```

Ele deve responder `{"status":"ok","service":"algorithm"}`.

### 3️⃣ Subir servidor MCP

```bash
cd lambda-lab-mcp-server
docker compose up -d --build
cd ..
```

### 4️⃣ Preencher `.env` do cliente

O cliente lê a configuração de `lambda-lab-client/.env`. Copie o template `.env.example` e o preencha:

```bash
cd lambda-lab-client
cp .env.example .env
```

| Campo                        | Descrição                                                   |
| ---------------------------- | ----------------------------------------------------------- |
| `GEMINI_API_KEY`             | Chave da API do Gemini                                      |
| `LLM_MODEL`                  | Modelo do agente, como `gemini-3.5-flash`                   |
| `LLM_REASONING_EFFORT`       | `low` (padrão), `medium` ou `high`                          |
| `JUDGE_MODEL`                | Modelo do juiz, de preferência um Pro                       |
| `CACHE_SIMILARITY_THRESHOLD` | Similaridade mínima para responder do cache (padrão `0.90`) |

A chave deve ser obtida através do [Google AI Studio](https://aistudio.google.com/apikey).

### 5️⃣ Subir cliente

```bash
docker compose up -d --build
cd ..
```

O build baixa o PyTorch (CPU-only) e o modelo de embeddings do cache, tendendo a ser a etapa mais demorada. Depois, o cliente sobe carregando o modelo `paraphrase-multilingual-MiniLM-L12-v2`.

Feito isso, acesse http://localhost:9002 e comece a interagir com o agente, por exemplo:

- Descreva "Encontre os índices dos dois números da lista [2, 7, 11, 15] que somam 9".
- Pergunte "Qual a complexidade do algoritmo de ordenação Bubble Sort?".
- Pergunte "Quem foi Marco Aurélio?".

Cada chamada de ferramenta aparece na conversa como uma etapa, com argumentos e resultado.

## ⚖️ Avaliação com LLM-as-a-Judge

Situado no diretório `lambda-lab-client/app`, o script `judge.py` envia ao agente, sem passar pelo cache, cada caso de `lambda-lab-client/judge_cases.json`, cada qual com um problema, seus parâmetros, a saída esperada e a complexidade de referência. O `JUDGE_MODEL` compara a resposta com a referência e dá notas de 1 a 5 em corretude, eficiência e clareza, com uma justificativa curta.

Para acioná-lo, é necessário ter o ambiente totalmente configurado (conforme descrito anteriormente). Execute-o com:

```bash
cd lambda-lab-client
docker compose exec client python /app/judge.py
```

É possível parametrizar a execução com as opções abaixo:

| Opção       | Descrição                                    |
| ----------- | -------------------------------------------- |
| `--limit N` | Avalia no máximo N casos ainda não avaliados |
| `--restart` | Descarta o relatório e avalia todos os casos |

Ex.:

```bash
docker compose exec client python /app/judge.py --limit 5 --restart
```

Cada caso é gravado em `lambda-lab-client/judge_report.json`. Uma execução interrompida continua de onde parou.

O relatório registra os modelos usados. Se `LLM_MODEL`, `LLM_REASONING_EFFORT` ou `JUDGE_MODEL` mudarem, o script pede `--restart` para não misturar notas.

O `.env.example` usa como juiz o `gemini-3.6-flash`, atualmente (24/10/2026) disponível no plano gratuito, e o `judge_report.json` versionado foi gerado com esse mesmo modelo, como registra o campo `configuration`. Como referência, um caso fácil gastou cerca de 17 mil tokens no agente e 1,5 mil no juiz.

## ⚠️ Limitações

- O sandbox não impede o código de ler arquivos do contêiner nem de acessar a rede, então não é adequado para código não confiável.
- Não há autenticação.
- Uma execução em andamento quando o serviço reinicia fica em `running` para sempre.
- Execuções que estouram o tempo ficam sem pico de memória.
- O `stdout` (saída padrão) é limitado a 10.000 caracteres.
- Cada correção vira um novo algoritmo, e o banco só é limpo com `docker compose down -v`.
- O limiar do cache semântico (0,90) foi calibrado com cerca de 50 pares de perguntas. Reformulações leves usam o cache, mas sinônimos costumam ficar abaixo do limiar, e perguntas que só trocam o nome do algoritmo, como sobre merge sort e heap sort, podem receber a resposta uma da outra.
- Trocar o modelo de embeddings exige alterar o `cache_service.py` e o `Dockerfile` do cliente e reconstruir a imagem.
- O histórico do chat fica na memória da sessão e se perde ao recarregar a página ou reiniciar o cliente.
- As notas do juiz variam um pouco entre rodadas, mesmo ao usar os mesmos modelos.
- O Chainlit exige `mcp<2`, por isso o cliente usa FastMCP 3 e o servidor, FastMCP 4.
- O Chainlit cria `.chainlit/` e `.files/` em `lambda-lab-client/app/` como root, e apagá-los no host exige `sudo`.

## 🧹 Remoção do ambiente

A partir do diretório raiz do projeto, execute os comandos na ordem abaixo:

```bash
docker compose -f lambda-lab-client/docker-compose.yml down -v --rmi local
docker compose -f lambda-lab-mcp-server/docker-compose.yml down -v --rmi local
docker compose -f lambda-lab-service/docker-compose.yml down -v --rmi local
```

A rede pertence ao serviço e só pode ser removida depois que os outros contêineres saírem.

O `-v` apaga os volumes (algoritmos, execuções e cache), e o `--rmi local` remove as imagens construídas, com o modelo de embeddings, mantendo a base `python:3.12-slim`.
