**Lambda Lab** é um sistema especialista entregue como chatbot, que gera algoritmos executáveis sob demanda, como funções lambda. A partir da descrição de um problema, ele escolhe uma estratégia de solução, escreve o código, valida a sintaxe, executa com os parâmetros informados pelo usuário, monitora tempo e memória e analisa a complexidade, corrigindo o código quando ele falha ou é ineficiente. É uma prova de conceito (PoC) feita para a disciplina, não um produto pronto para produção.

O projeto tem três módulos: um serviço REST que valida, guarda e executa algoritmos, um servidor MCP que expõe esse serviço como ferramentas e um cliente Chainlit, em que o agente conversa com o Gemini e usa essas ferramentas. As partes avaliadas na disciplina ficam nestes arquivos.

| Parte avaliada              | Onde fica                                                                                     |
| --------------------------- | --------------------------------------------------------------------------------------------- |
| Motor de inferência com LLM | `client/app/services/agent_service.py`                                                        |
| Cache semântico             | `client/app/services/cache_service.py`                                                        |
| Ferramentas MCP             | `mcp-server/app/tools.py`                                                                     |
| LLM-as-a-Judge              | `client/app/judge.py`, `client/app/services/judge_service.py` e `client/app/judge_cases.json` |

## 🧩 Módulos

A ordem abaixo é também a ordem de subida. O servidor MCP depende da rede e do serviço criados pelo primeiro módulo, e o cliente depende do servidor MCP.

### ⚙️ `service/`

![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![FastAPI](https://img.shields.io/badge/fastapi-109989?style=for-the-badge&logo=FASTAPI&logoColor=white)
![SQLite](https://img.shields.io/badge/sqlite-%2307405e.svg?style=for-the-badge&logo=sqlite&logoColor=white)
![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=for-the-badge&logo=docker&logoColor=white)

É uma aplicação FastAPI com SQLModel e SQLite, na porta 9000. Algoritmos e execuções ficam em `/data/service.db`, dentro do volume `sqlitedata`, e cada execução roda em segundo plano, num processo Python separado.

| Arquivo          | Responsabilidade                                                          |
| ---------------- | ------------------------------------------------------------------------- |
| `__main__.py`    | Monta o app FastAPI, cria as tabelas e sobe o uvicorn na porta 9000       |
| `database.py`    | Cria a engine a partir de `DATABASE_URL` e fornece a sessão               |
| `schemas.py`     | Modelos para entrada e saída de dados                                     |
| `models.py`      | Mapeamento das tabelas `algorithm` e `execution` em modelos (entidades)   |
| `services.py`    | Validação, execução isolada e monitoramento, para manter as rotas enxutas |
| `controllers.py` | Rotas HTTP                                                                |

Não há rotas `PATCH` nem `DELETE`, então a IA não altera nem apaga o histórico. Execuções também nunca vêm de cache: cada pedido roda o algoritmo de novo. A documentação interativa fica em `http://localhost:9000/docs`.

| Rota                                         | Descrição                                                                                                                                      |
| -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /health`                                | Retorna o estado do serviço                                                                                                                    |
| `POST /algorithms/validate`                  | Valida a sintaxe e a função de entrada sem salvar e, em caso de erro, devolve linha, coluna e mensagem                                         |
| `POST /algorithms`                           | Valida e salva o algoritmo (`201`), ou devolve `400` com os mesmos detalhes do erro                                                            |
| `GET /algorithms`                            | Lista com `limit` (padrão 50) e `offset` (padrão 0)                                                                                            |
| `GET /algorithms/search`                     | Filtra por `name` e `description`, com busca parcial e sem diferenciar maiúsculas                                                              |
| `GET /algorithms/{algorithm_id}`             | Busca por ID, ou `404`                                                                                                                         |
| `POST /algorithms/{algorithm_id}/executions` | Recebe os `arguments`, inicia a execução em segundo plano e devolve `202` com a execução `pending`                                             |
| `GET /executions`                            | Lista com `limit` e `offset`                                                                                                                   |
| `GET /executions/search`                     | Filtra por `status` e `algorithm_id`, como em `?status=completed`                                                                              |
| `GET /executions/{execution_id}`             | Monitora a execução: status, resultado, `stdout`, erro, duração e pico de memória, além do tempo decorrido (`elapsed_in_ms`) enquanto ela roda |

O código precisa definir a função de entrada (`solve`, por padrão) no nível do módulo. A validação usa `ast.parse` e compila a árvore, o que também pega erros como um `return` fora de função. Na execução, a função é chamada com os `arguments` como argumentos nomeados, em `solve(**arguments)`.

Cada execução roda como o usuário `nobody`, numa pasta temporária, com um ambiente mínimo e com limites de 10 segundos e 256 MB, por isso não consegue gravar em `/data`. O status vai de `pending` para `running` e termina em `completed`, `failed` ou `timed_out`. Os prints do algoritmo ficam no campo `stdout`, separados do resultado, e resultados que não são JSON são guardados com `repr`. O `duration_in_ms` mede só a chamada da função, e o `peak_memory_in_kb` vem do `getrusage` do processo filho, incluindo cerca de 9 MB do próprio interpretador.

---

### 🔌 `mcp-server/`

![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![MCP](https://img.shields.io/badge/mcp-%23000000.svg?style=for-the-badge&logo=modelcontextprotocol&logoColor=white)
![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=for-the-badge&logo=docker&logoColor=white)

O servidor usa FastMCP com transporte `streamable-http`, na porta 9001 e no caminho `/mcp`. Cada ferramenta espelha uma rota do serviço e traduz a chamada numa requisição HTTP para `http://lambda-lab-service:9000`.

| Ferramenta                       | Rota                                         |
| -------------------------------- | -------------------------------------------- |
| `check_algorithm_service_health` | `GET /health`                                |
| `validate_algorithm`             | `POST /algorithms/validate`                  |
| `create_algorithm`               | `POST /algorithms`                           |
| `list_algorithms`                | `GET /algorithms`                            |
| `search_algorithms`              | `GET /algorithms/search`                     |
| `get_algorithm`                  | `GET /algorithms/{algorithm_id}`             |
| `execute_algorithm`              | `POST /algorithms/{algorithm_id}/executions` |
| `get_execution`                  | `GET /executions/{execution_id}`             |
| `list_executions`                | `GET /executions`                            |
| `search_executions`              | `GET /executions/search`                     |

O `execute_algorithm` espera até 5 segundos pelo fim da execução, então na maioria dos casos já devolve o resultado. Se ela ainda estiver rodando, a IA acompanha com `get_execution`.

| Arquivo       | Responsabilidade                                                               |
| ------------- | ------------------------------------------------------------------------------ |
| `__main__.py` | Registra as ferramentas no FastMCP e sobe o transporte HTTP                    |
| `client.py`   | Chama o serviço com httpx e converte falha de rede ou erro HTTP em `ToolError` |
| `models.py`   | Modelos Pydantic dos recursos devolvidos                                       |
| `tools.py`    | As ferramentas, cujas docstrings a IA lê como documentação                     |

O compose deste módulo declara a rede `lambda-lab-network` como externa, por isso o serviço precisa estar de pé antes.

---

### 💬 `client/`

![Chainlit](https://img.shields.io/badge/chainlit-F80061?style=for-the-badge&logoColor=white)
![Gemini](https://img.shields.io/badge/gemini-%238E75B2.svg?style=for-the-badge&logo=googlegemini&logoColor=white)
![SQLite](https://img.shields.io/badge/sqlite-%2307405e.svg?style=for-the-badge&logo=sqlite&logoColor=white)
![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=for-the-badge&logo=docker&logoColor=white)

É um chat Chainlit na porta 9002. Ele fala com o Gemini pelo endpoint compatível com a OpenAI, usando o SDK `openai`, e com o servidor MCP pelo cliente do FastMCP, em `http://lambda-lab-mcp-server:9001/mcp`. O cache semântico fica em `/data/client.db`, no volume `sqlitedata` deste módulo.

| Arquivo                     | Responsabilidade                                                            |
| --------------------------- | --------------------------------------------------------------------------- |
| `__main__.py`               | Sobe o Chainlit em `0.0.0.0:9002`                                           |
| `controllers.py`            | Handlers do Chainlit, que mostram cada chamada de ferramenta como uma etapa |
| `database.py`               | Engine e sessão do cache, a partir de `CACHE_DATABASE_URL`                  |
| `models.py`                 | Tabela do cache semântico                                                   |
| `services/agent_service.py` | Motor de inferência: prompt de sistema e laço entre o LLM e as ferramentas  |
| `services/llm_service.py`   | Chat e embeddings do Gemini, com novas tentativas em `429` e `503`          |
| `services/cache_service.py` | Busca e gravação no cache semântico                                         |
| `services/tools_service.py` | Cliente MCP, que lista e chama as ferramentas                               |
| `services/judge_service.py` | Prompt do juiz e leitura das notas                                          |
| `judge.py`                  | Script de avaliação LLM-as-a-Judge                                          |
| `judge_cases.json`          | Os 18 casos de avaliação                                                    |
| `chainlit.md`               | Apresentação do Lambda Lab na tela do chat                                  |

O prompt de sistema, em português, guia o agente em sete passos: entender o problema, escolher e justificar uma estratégia, escrever a função `solve` e validá-la, salvá-la e executá-la com os parâmetros do usuário (ou com um exemplo pequeno, avisando), relatar resultado, tempo e memória, explicar a complexidade de tempo e espaço e, se a execução falhar, estourar o tempo ou for ineficiente, corrigir o código, em até 3 tentativas. Perguntas conceituais são respondidas direto, sem ferramentas, e o laço entre o LLM e as ferramentas tem no máximo 26 passos. As chamadas do agente usam `reasoning_effort` (`low`, por padrão) para economizar tokens.

O cache semântico compara o embedding da pergunta com os já guardados, por similaridade de cosseno, e responde do cache quando ela passa do limiar (0,90, por padrão). Só a primeira mensagem de cada chat é consultada e guardada, e só respostas dadas sem ferramentas entram no cache, já que resultados de execução são dados dinâmicos. Quando a resposta vem do cache, o chat avisa e mostra a similaridade.

## 🛠️ Instalação e execução

### 1️⃣ Pré-requisitos

Sistema operacional Linux, macOS ou Windows com WSL, além de Docker com o plugin Compose. Os três módulos constroem a própria imagem a partir de `python:3.12-slim` e instalam o `requirements.txt` no build, então não é preciso ter Python no host. Também é preciso uma chave da API do Gemini.

As portas 9000, 9001 e 9002 precisam estar livres. Se alguma estiver ocupada, o compose falha na subida.

### 2️⃣ Subir o serviço

```bash
cd service
docker compose up -d --build
cd ..
```

O comando cria a rede `lambda-lab-network` e o volume do SQLite. Antes de seguir, chame o `/health`.

```bash
curl http://localhost:9000/health
```

Ele deve responder `{"status":"ok","service":"algorithm"}`.

### 3️⃣ Subir o servidor MCP

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

São seis campos.

| Campo                        | Descrição                                                           |
| ---------------------------- | ------------------------------------------------------------------- |
| `GEMINI_API_KEY`             | Chave da API do Gemini                                              |
| `LLM_MODEL`                  | Modelo do agente, como `gemini-3.5-flash`                           |
| `LLM_REASONING_EFFORT`       | Esforço de raciocínio do agente: `low` (padrão), `medium` ou `high` |
| `EMBEDDING_MODEL`            | Modelo de embeddings do cache, como `gemini-embedding-001`          |
| `JUDGE_MODEL`                | Modelo do juiz, mais forte que o do agente, de preferência um Pro   |
| `CACHE_SIMILARITY_THRESHOLD` | Similaridade mínima para responder do cache (padrão `0.90`)         |

A chave deve ser obtida através do [Google AI Studio](https://aistudio.google.com/apikey). Na época dos testes, os modelos `gemini-2.5` já não estavam disponíveis para contas novas, e os modelos Pro só funcionavam com faturamento ativo.

### 5️⃣ Subir o cliente

```bash
docker compose up -d --build
```

Abra `http://localhost:9002` e descreva um problema, como "Encontre os índices dos dois números da lista [2, 7, 11, 15] que somam 9". Cada chamada de ferramenta aparece na conversa como uma etapa, com os argumentos e o resultado. Feito isso, é só usar o chat e se divertir 😎👍.

## ⚖️ Avaliação com LLM-as-a-Judge

O `judge.py` roda dentro do contêiner do cliente. Cada caso de `judge_cases.json` traz o problema, os parâmetros de entrada, a saída esperada e a complexidade de referência, e vai para o agente sem passar pelo cache. Em seguida, o `JUDGE_MODEL` recebe o problema, a referência e a resposta do agente e dá notas de 1 a 5 em corretude, eficiência e clareza, com uma justificativa curta.

Na pasta `client`, execute:

```bash
docker compose exec client python /app/judge.py
```

| Opção       | Descrição                                                  |
| ----------- | ---------------------------------------------------------- |
| `--limit N` | Avalia no máximo N casos ainda não avaliados               |
| `--restart` | Descarta o relatório atual e avalia todos os casos de novo |

O script mostra as notas de cada caso e as médias, e grava cada caso em `client/app/judge_report.json` assim que ele termina, com as notas, a justificativa, as ferramentas chamadas, a duração, os tokens do agente e do juiz e a resposta completa. Se a execução parar no meio, basta rodar de novo, já que os casos avaliados são pulados. Diante de limite de requisições (`429`) ou sobrecarga (`503`), ele espera e tenta de novo; com o saldo pré-pago esgotado (`402`), para na hora.

O relatório guarda os modelos usados. Se `LLM_MODEL`, `LLM_REASONING_EFFORT` ou `JUDGE_MODEL` mudarem, o script não mistura as notas e pede `--restart`. Para ter uma ideia do custo, um caso fácil gastou cerca de 15 mil tokens no agente e 1,5 mil no juiz, e casos difíceis ou com correções gastam mais.

## ⚠️ Limitações

Como prova de conceito, o Lambda Lab simplifica algumas partes.

- O sandbox é básico: usuário sem privilégios, pasta temporária, ambiente mínimo e limites de tempo e memória. O código gerado ainda lê arquivos do contêiner e acessa a rede, então não serve para rodar código não confiável em produção.
- Execuções que estouram o tempo ficam sem pico de memória, porque o processo é encerrado antes da medição.
- O `stdout` de cada execução é cortado em 10.000 caracteres.
- O cache semântico só cobre a primeira mensagem de cada chat, quando respondida sem ferramentas, e o limiar de 0,90 não foi calibrado com um conjunto de perguntas.
- Não há autenticação em nenhum módulo.
- O histórico do chat fica só na memória da sessão e some ao recarregar a página ou reiniciar o cliente.
- Algoritmos e execuções só se acumulam, porque cada correção vira um novo algoritmo, e só o `down -v` limpa o banco.
- Se o serviço reiniciar durante uma execução, ela fica em `running` para sempre.
- No plano gratuito, a conta usada nos testes tinha cerca de 20 requisições por dia por modelo e nenhuma cota para modelos Pro, então uma rodada completa do juiz precisa de faturamento ativo.
- As notas do juiz podem variar um pouco entre rodadas, já que os modelos Gemini 3 devem rodar na temperatura padrão.
- O Chainlit exige `mcp<2`, então o cliente usa o FastMCP 3, enquanto o servidor usa o FastMCP 4.
- O Chainlit cria `.chainlit/` e `.files/` em `client/app/` como root, e apagá-los no host exige `sudo`.

## 🧹 Remoção do ambiente

Da raiz do repositório, execute:

```bash
docker compose -f client/docker-compose.yml down -v --rmi local
docker compose -f mcp-server/docker-compose.yml down -v --rmi local
docker compose -f service/docker-compose.yml down -v --rmi local
```

A rede `lambda-lab-network` pertence ao compose do serviço, e o Docker não apaga uma rede que ainda tem contêiner conectado, então o cliente e o servidor MCP precisam sair antes, portanto, a ordem acima é importante.

O `-v` apaga os volumes, e com eles os algoritmos, as execuções e o cache semântico. O `--rmi local` remove as imagens construídas aqui, mas mantém a imagem base `python:3.12-slim`, que pode ser removida com `docker rmi python:3.12-slim` se nenhum outro projeto seu a usa.
