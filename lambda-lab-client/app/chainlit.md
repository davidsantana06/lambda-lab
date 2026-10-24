# Lambda Lab 🧪

O Lambda Lab é um sistema especialista que cria algoritmos executáveis sob demanda, como funções lambda. Descreva um problema e ele:

1. escolhe uma estratégia de solução e explica por quê;
2. escreve o código em Python e valida a sintaxe;
3. executa o código com os parâmetros que você informar;
4. mede o tempo de execução e o pico de memória;
5. explica a complexidade de tempo e de espaço;
6. corrige o código quando a execução falha ou fica lenta demais.

Cada chamada de ferramenta aparece na conversa como uma etapa, com os argumentos e o resultado. Perguntas conceituais são respondidas direto, sem executar nada, e uma pergunta parecida com outra já feita pode vir do cache semântico. Uma pergunta repetida na mesma conversa vem do cache da conversa, se não tiver usado ferramentas.

## Exemplos de pedidos

- Qual a diferença entre programação dinâmica e divisão e conquista?
- Encontre os índices dos dois números da lista `[2, 7, 11, 15]` que somam `9`.
- Calcule o número de Fibonacci de posição `90` e diga quanto tempo e memória a execução usou.
