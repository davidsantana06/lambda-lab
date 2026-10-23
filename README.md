**Lambda Lab** é um sistema especialista em formato de chatbot que gera algoritmos executáveis sob demanda. A partir da descrição de um problema, ele escolhe uma estratégia, escreve o código, valida a sintaxe, executa com os parâmetros do usuário, mede tempo e memória, analisa a complexidade e corrige o código quando ele falha ou é ineficiente. É uma prova de conceito, não um produto pronto para produção.

## 🧩 Módulos

São três módulos, listados na ordem em que devem subir: o serviço cria a rede usada pelo servidor MCP, e o cliente depende do servidor MCP.

### ⚙️ `service/`

API FastAPI com SQLModel e SQLite, na porta 9000. Algoritmos e execuções ficam em `/data/service.db` (volume `sqlitedata`), e cada execução roda em segundo plano, num processo Python separado.

| Arquivo          | Responsabilidade                              |
| ---------------- | --------------------------------------------- |
| `__main__.py`    | Monta o app, cria as tabelas e sobe o uvicorn |
| `database.py`    | Engine e sessão, a partir de `DATABASE_URL`   |
| `schemas.py`     | Modelos de entrada e saída                    |
| `models.py`      | Tabelas `algorithm` e `execution`             |
| `services.py`    | Validação, execução isolada e monitoramento   |
| `controllers.py` | Rotas HTTP                                    |

A coluna "Ferramenta MCP" indica a ferramenta correspondente no `mcp-server/`.

| Rota                                         | Ferramenta MCP                   | Descrição                                                                                           |
| -------------------------------------------- | -------------------------------- | --------------------------------------------------------------------------------------------------- |
| `GET /health`                                | `check_algorithm_service_health` | Estado do serviço                                                                                   |
| `POST /algorithms/validate`                  | `validate_algorithm`             | Valida sem salvar; em caso de erro, devolve linha, coluna e mensagem                                |
| `POST /algorithms`                           | `create_algorithm`               | Valida e salva (`201`) ou devolve `400` com o erro                                                  |
| `GET /algorithms`                            | `list_algorithms`                | Lista paginada (`limit` 50 e `offset` 0, por padrão)                                                |
| `GET /algorithms/search`                     | `search_algorithms`              | Busca parcial por `name` e `description`, sem diferenciar maiúsculas                                |
| `GET /algorithms/{algorithm_id}`             | `get_algorithm`                  | Busca por ID, ou `404`                                                                              |
| `POST /algorithms/{algorithm_id}/executions` | `execute_algorithm`              | Inicia a execução com os `arguments` e devolve `202` com status `pending`                           |
| `GET /executions`                            | `list_executions`                | Lista paginada                                                                                      |
| `GET /executions/search`                     | `search_executions`              | Filtra por `status` e `algorithm_id`                                                                |
| `GET /executions/{execution_id}`             | `get_execution`                  | Status, resultado, `stdout`, erro, duração e pico de memória (e `elapsed_in_ms` durante a execução) |

Não há rotas de alteração ou remoção, e toda execução roda o algoritmo de novo, sem cache. A documentação interativa fica em `http://localhost:9000/docs`.

O código deve definir a função de entrada (`solve`, por padrão) no nível do módulo. A validação usa `ast.parse` e compila a árvore, o que também detecta erros como `return` fora de função. A função é chamada como `solve(**arguments)`.

Cada execução roda como `nobody`, numa pasta temporária e com ambiente mínimo, limitada a 10 s e 256 MB. O status vai de `pending` a `running` e termina em `completed`, `failed` ou `timed_out`. O `stdout` fica separado do resultado, e resultados que não são JSON são guardados com `repr`. O `duration_in_ms` mede só a chamada da função. O `peak_memory_in_kb` vem do `getrusage` do processo filho e inclui cerca de 9 MB do interpretador.

---

### 🔌 `mcp-server/`

Servidor FastMCP com transporte `streamable-http`, na porta 9001 e no caminho `/mcp`. Cada ferramenta (ver tabela acima) vira uma requisição HTTP para `http://lambda-lab-service:9000`. O `execute_algorithm` espera até 5 segundos pelo fim da execução. Se ela ainda não terminou, o agente acompanha com `get_execution`.

| Arquivo       | Responsabilidade                                                   |
| ------------- | ------------------------------------------------------------------ |
| `__main__.py` | Registra as ferramentas e sobe o transporte HTTP                   |
| `client.py`   | Chama o serviço com httpx e converte falhas em `ToolError`         |
| `models.py`   | Modelos Pydantic dos recursos devolvidos                           |
| `tools.py`    | Ferramentas, cujas docstrings servem de documentação para o agente |

---

### 💬 `client/`

Chat Chainlit na porta 9002. Conversa com o Gemini pelo endpoint compatível com a OpenAI (SDK `openai`) e com o servidor MCP pelo cliente FastMCP, em `http://lambda-lab-mcp-server:9001/mcp`. O cache semântico fica no ChromaDB, em `/data/cache` (volume `chromadata`).

| Arquivo                     | Responsabilidade                                              |
| --------------------------- | ------------------------------------------------------------- |
| `__main__.py`               | Sobe o Chainlit em `0.0.0.0:9002`                             |
| `controllers.py`            | Handlers do Chainlit, que exibem cada chamada de ferramenta   |
| `services/agent_service.py` | Motor de inferência: prompt de sistema e laço LLM–ferramentas |
| `services/llm_service.py`   | Chat com o Gemini, com novas tentativas em `429`/`503`        |
| `services/cache_service.py` | Embeddings locais e coleção do cache semântico no ChromaDB    |
| `services/tools_service.py` | Cliente MCP                                                   |
| `services/judge_service.py` | Prompt do juiz e leitura das notas                            |
| `judge.py`                  | Script de avaliação LLM-as-a-Judge                            |
| `judge_cases.json`          | Os 18 casos de avaliação                                      |
| `chainlit.md`               | Tela de apresentação do chat                                  |

O prompt de sistema orienta o agente a entender o problema e justificar a estratégia. Em seguida, ele escreve e valida a função `solve` e a salva e executa (com um exemplo pequeno, se o usuário não der parâmetros). Por fim, relata resultado, tempo, memória e complexidade e corrige o código em até 3 tentativas. Perguntas conceituais são respondidas sem ferramentas. O laço entre LLM e ferramentas tem no máximo 26 passos, e as chamadas usam `reasoning_effort` (`low`, por padrão).

O cache semântico gera o embedding da pergunta localmente, com o modelo multilíngue `paraphrase-multilingual-MiniLM-L12-v2` do sentence-transformers, sem chamar o Gemini. Uma coleção do ChromaDB guarda pergunta, embedding e resposta e devolve a distância de cosseno, convertida em similaridade (1 − distância). Acima do limiar (0,90, por padrão), a resposta vem do cache, e o chat mostra a similaridade. Só a primeira mensagem de cada chat é consultada, e só respostas dadas sem ferramentas são guardadas.

## 🛠️ Instalação e execução

### 1️⃣ Pré-requisitos

Sistema operacional Linux, macOS ou Windows com WSL, além de Docker com o plugin Compose e uma chave da API do Gemini. Os três módulos constroem a própria imagem a partir de `python:3.12-slim` e instalam o `requirements.txt` no build, então não é preciso ter Python no host.

A imagem do cliente ocupa cerca de 3,5 GB, por causa do PyTorch para CPU e do modelo de embeddings, e o primeiro build dela levou cerca de 11 minutos nos testes, conforme a conexão. Reserve pelo menos 5 GB livres em disco para as três imagens.

As portas 9000, 9001 e 9002 precisam estar livres. Se alguma estiver ocupada, o compose falha na subida.

### 2️⃣ Subir serviço

```bash
cd service
docker compose up -d --build
cd ..
```

O comando cria a rede `lambda-lab-network` e o volume `sqlitedata`. Antes de seguir, chame o `/health`.

```bash
curl http://localhost:9000/health
```

Ele deve responder `{"status":"ok","service":"algorithm"}`. O serviço leva alguns segundos para subir, então, se o `curl` falhar logo após o `up`, espere um pouco e repita.

### 3️⃣ Subir servidor MCP

```bash
cd mcp-server
docker compose up -d --build
cd ..
```

### 4️⃣ Preencher `.env` do cliente

O cliente lê a configuração de `client/.env`. Copie o template `.env.example` e preencha o seu.

```bash
cd client
cp .env.example .env
```

| Campo                        | Descrição                                                   |
| ---------------------------- | ----------------------------------------------------------- |
| `GEMINI_API_KEY`             | Chave da API do Gemini                                      |
| `LLM_MODEL`                  | Modelo do agente, como `gemini-3.5-flash`                   |
| `LLM_REASONING_EFFORT`       | `low` (padrão), `medium` ou `high`                          |
| `JUDGE_MODEL`                | Modelo do juiz, de preferência um Pro                       |
| `CACHE_SIMILARITY_THRESHOLD` | Similaridade mínima para responder do cache (padrão `0.90`) |

A chave deve ser obtida através do [Google AI Studio](https://aistudio.google.com/apikey). Nos testes, contas novas já não tinham acesso aos modelos `gemini-2.5`, e os modelos Pro exigiam faturamento ativo.

### 5️⃣ Subir cliente

```bash
docker compose up -d --build
```

O build baixa o PyTorch para CPU e o modelo de embeddings do cache, por isso leva alguns minutos e gera uma imagem de cerca de 3,5 GB. Depois, o cliente sobe em poucos segundos, sem acessar a rede para carregar o modelo.

Abra `http://localhost:9002` e descreva um problema, como "Encontre os índices dos dois números da lista [2, 7, 11, 15] que somam 9". Cada chamada de ferramenta aparece na conversa como uma etapa, com argumentos e resultado.

## ⚖️ Avaliação com LLM-as-a-Judge

O `judge.py` envia ao agente, sem passar pelo cache, cada caso de `judge_cases.json`. Cada caso traz o problema, os parâmetros, a saída esperada e a complexidade de referência. O `JUDGE_MODEL` compara a resposta com a referência e dá notas de 1 a 5 em corretude, eficiência e clareza, com uma justificativa curta. Na pasta `client`, execute:

```bash
docker compose exec client python /app/judge.py
```

| Opção       | Descrição                                    |
| ----------- | -------------------------------------------- |
| `--limit N` | Avalia no máximo N casos ainda não avaliados |
| `--restart` | Descarta o relatório e avalia todos os casos |

Cada caso é gravado em `client/app/judge_report.json` assim que termina, com notas, justificativa, ferramentas chamadas, duração, tokens e resposta completa. Uma execução interrompida continua de onde parou. Em `429` ou `503`, o script espera e tenta de novo. Em `402` (saldo pré-pago esgotado), ele para.

O relatório registra os modelos usados. Se `LLM_MODEL`, `LLM_REASONING_EFFORT` ou `JUDGE_MODEL` mudarem, o script pede `--restart` para não misturar notas. Como referência, um caso fácil gastou cerca de 15 mil tokens no agente e 1,5 mil no juiz.

## ⚠️ Limitações

- O sandbox não impede o código de ler arquivos do contêiner nem de acessar a rede, então não é adequado para código não confiável.
- Execuções que estouram o tempo ficam sem pico de memória.
- O `stdout` é cortado em 10.000 caracteres.
- O limiar do cache semântico (0,90) foi calibrado com cerca de 50 pares de perguntas. Reformulações leves usam o cache, mas sinônimos costumam ficar abaixo do limiar, e perguntas que só trocam o nome do algoritmo, como sobre merge sort e heap sort, podem receber a resposta uma da outra.
- Trocar o modelo de embeddings exige alterar o `cache_service.py` e o `Dockerfile` do cliente e reconstruir a imagem.
- Não há autenticação.
- O histórico do chat fica na memória da sessão e se perde ao recarregar a página ou reiniciar o cliente.
- Cada correção vira um novo algoritmo, e o banco só é limpo com `down -v`.
- Uma execução em andamento quando o serviço reinicia fica em `running` para sempre.
- No plano gratuito, a conta de testes tinha cerca de 20 requisições diárias por modelo e nenhuma cota para modelos Pro, então uma rodada completa do juiz exige faturamento.
- As notas do juiz variam um pouco entre rodadas, pois os modelos Gemini 3 rodam na temperatura padrão.
- O Chainlit exige `mcp<2`, por isso o cliente usa FastMCP 3 e o servidor, FastMCP 4.
- O Chainlit cria `.chainlit/` e `.files/` em `client/app/` como root, e apagá-los no host exige `sudo`.

## 🧹 Remoção do ambiente

Da raiz do repositório, execute os comandos nesta ordem. A rede pertence ao serviço e só pode ser removida depois que os outros contêineres saírem.

```bash
docker compose -f client/docker-compose.yml down -v --rmi local
docker compose -f mcp-server/docker-compose.yml down -v --rmi local
docker compose -f service/docker-compose.yml down -v --rmi local
```

O `-v` apaga os volumes (algoritmos, execuções e cache), e o `--rmi local` remove as imagens construídas, com o modelo de embeddings, mantendo a base `python:3.12-slim`.
