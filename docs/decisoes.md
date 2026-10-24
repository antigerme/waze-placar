# Decisões, becos sem saída e ordens de grandeza

O que a referência da API não cobre: por que o projeto é como é, o que já foi
testado e descartado, e com que números uma execução saudável se parece.

Escrito para evitar que alguém — inclusive eu, numa sessão nova — refaça
caminho que já foi andado.

---

## Erros que este projeto já cometeu

Cada um destes custou uma conclusão errada antes de virar linha de código.
Estão aqui porque são fáceis de repetir.

**Cortar o painel de estados nas 14 UFs de maior volume.** A tabela mostrava
só as primeiras por edições, com um `.slice(0, 14)` herdado da tabela
principal — onde o corte existe por desempenho, com milhares de linhas. Aqui o
teto é 27 UFs, então o corte não poupava nada e escondia justamente o que o
painel mede: os estados frágeis, de fator 1, são os de baixo volume que iam
para o fim da lista. O KPI do topo dizia "19 estados dependem de um único
editor" e a tabela deixava ver 7 deles; os 12 mais extremos — inclusive UFs com
um único editor ativo respondendo por 100% — ficavam abaixo do corte. O número
que o painel existe para dar não fechava com o que ele mostrava. Hoje lista
todas as UFs com atividade e, ao final, as que não tiveram nenhuma edição na
janela como linha própria ("AP — sem atividade na janela") — o fator de ônibus
no extremo, ninguém editando, virou linha visível em vez de ausência silenciosa.

**Concluir que o `lookbackPeriod` era inerte.** Foi sondado com valores
inventados (`LAST_7_DAYS` e afins), o servidor respondeu 200 com o payload de
`ALL_TIME`, e a leitura foi "o parâmetro não funciona". Funciona; só existem
três valores. Sondar enum inventando nome não prova nada quando a API não
valida entrada.

**Achar que o funil de entrada tinha secado.** O universo vinha só dos
rankings, que excluem novato por construção — quem tem três edições não pontua
o bastante para entrar. A conclusão "16 novos no último ano, a comunidade parou
de receber gente" estava errada por amostragem: `Mentoring/NewEditors` lista
319. Antes de afirmar que algo não existe, verifique se a fonte conseguiria
mostrá-lo.

**Quase publicar que mentoria dá 100% de retenção.** Só 10 dos 88 afilhados
estavam no universo, e estar no universo já exige ter aparecido num ranking —
ou seja, a amostra era só de quem deu certo. Buscando o perfil dos que faltavam,
36% contra 11%. Sempre pergunte por que um registro está na amostra.

**Validar layout por métrica em vez de olhar.** Checagens em Python dizendo
"sem overflow" enquanto a tabela principal estourava o container em todas as
larguras — o sintoma estava escondido atrás de barras de rolagem que pareciam
intencionais. Daí o `scripts/auditar-layout.mjs`.

**Deixar afirmação escrita à mão na página.** Textos como "não há pico de fim
de semana" e "as safras recentes aparecem mais altas" ficaram falsos quando os
dados mudaram, sem ninguém perceber. Hoje nenhum texto da página tem número
literal: ou é descrição do método, ou é medido na coleta.

**Descartar dado na normalização.** O `normaliza_perfil` guardava
`menteesCount` e jogava fora a lista `mentees[]` que vinha na mesma resposta.
A análise de mentoria ficou impossível até alguém notar. Coletar é caro;
descartar campo na entrada é desperdício silencioso.

**Publicar zero em vez de não publicar.** O `--sem-perfis` saía com código 0 e
uma página inteira de zeros: KPIs zerados, as quatro abas dizendo zero editor,
painéis afirmando que ninguém editou, e "1 edições em 90 dias" — a guarda de
divisão por zero vazando para dentro do texto. Pior, a mensagem de erro do
próprio `placar.py` recomendava a flag quando o Descartes recusava a sessão,
conselho que trocava a página boa de ontem por essa. Zero medido e zero por não
ter medido são coisas diferentes: hoje a página detecta que não há vetor diário
e diz que só tem o acumulado, em vez de afirmar ausência de atividade.

**Checar só metade do texto e achar que checou tudo.** A regra "nada de número
à mão" existia desde cedo, e o `verificar.py` a cobrava — mas só dentro de
`<p>` e `<h2>`. A maior parte do texto da página não mora lá: mora nas dicas de
hover, nos `title=` das colunas, nos rótulos das abas e nos KPIs. Passaram
"últimos 90 dias", "45 anteriores", "15 blocos de 6 dias", "50 pessoas", "60 ou
mais dos últimos 90 dias" — uma dúzia de lugares que ficariam falsos no dia em
que a constante mudasse, com a verificação dando ok o tempo todo. Uma checagem
que cobre parte do alvo é pior que nenhuma: ela dá confiança.

**Afirmar o formato do dado, não só o valor.** A página dizia que o gradiente
de atividade por nível "sobe sem exceção do nível 1 ao 6". Era verdade quando
foi escrito. Mas o `decisoes.md` já registrava, duas seções abaixo, que esse
gradiente é o canário de coleta quebrada — ou seja, o dia em que a frase ficar
falsa é exatamente o dia em que ela mais engana. Hoje o script confere e diz
onde quebra. Vale para todo "sobe", "é raro", "quase todos": meça, ou não
escreva.

**Achar que dava para deduzir o significado de `rankLocked` do payload.** O
campo vinha em 47 dos 172 candidatos brasileiros e o dado não dizia se era
sanção ou rotina administrativa — proporção alta demais para parecer punição,
o que puxava para o palpite de que fosse rotina. É sanção: confirmado por Champ
da comunidade brasileira. A exclusão, decidida por precaução quando o
significado era desconhecido, estava certa. Quando o campo é sobre pessoa
nomeada e o significado é ambíguo, exclua primeiro e pergunte a quem sabe —
inverter depois é barato, despublicar não é.

**Inventar o mecanismo ao dar a ressalva.** A nota de mentoria dizia que os
dois números não provam causa "porque quem procura mentor provavelmente já é
quem tenderia a continuar". A ressalva estava certa, a explicação não era
medida — e provavelmente estava invertida, já que no Waze é o mentor que
adiciona o afilhado (`AddMentee`). Dar a ressalva não autoriza inventar a razão.

**Chamar de "a caminho" quem estava parado.** O `rankCandidates` lista quem
bate o critério de edições acumuladas, não quem está editando — são coisas
diferentes, e a diferença é grande: 69 dos 120 candidatos brasileiros não
tinham nenhuma edição na janela. Pior no lugar mais visível, a coluna de quem
está mais perto: os seis primeiros estavam todos parados, o primeiro deles a
dez edições do próximo nível e sem editar havia meses. O painel prometia
movimento onde não havia nenhum. Hoje só entra quem editou na janela — entre
esses, a mediana de silêncio é de seis dias.

Vale para qualquer lista que a API rotule: o rótulo dela é sobre o acumulado, o
placar é sobre atividade. Confira em qual dos dois o painel está falando.

**Quase transformar percentual em "faltam N edições".** O `fracToNextRank` do
`rankCandidates` parece progresso em edições, e para quem sai do primeiro nível
é mesmo: o denominador dá 3.000 cravado para todos os candidatos do mundo. A
tentação era publicar "faltam N edições para o nível X" em toda a tabela.
Medindo, o denominador do segundo nível em diante muda de pessoa para pessoa —
25.735 para um, 25.270 para outro — e o que entra nessa conta não está no
payload. Hoje o script mede o limiar por nível e só cita o número onde ele é
único; nos outros mostra o percentual e diz que não sabe quanto falta.

**Seletor CSS sem `>` estragando todo gráfico de barra.** A regra que trunca o
rótulo comprido — criada para nome de cidade não invadir o gráfico — era
`.barra span:first-child`. Sem o `>`, ela casa qualquer span que seja primeiro
filho **dentro** da barra, e a barra azul é o primeiro filho do trilho. Todo
gráfico ficou com teto de 8rem: acima de uns dois terços, valores diferentes
desenhavam do mesmo tamanho. O ritmo semanal mostrava os sete dias iguais com
205 mil e 279 mil edições lado a lado, e o top 100 da concentração pintava 66%
dizendo 98%.

Passou meses assim porque nada estourava: a barra desenhava *menos*, não mais,
e o auditor só procurava transbordo. Hoje ele compara a largura que o CSS pede
com a que o navegador pinta, em toda barra da página. Foi um leitor que viu,
não a ferramenta.

**Reusar perfis de outro dia e ler o resultado como se fosse de hoje.** O
`--perfis` existe para não recoletar o universo a cada mudança de layout, e
funciona — só que o vetor diário vem ancorado no dia da coleta enquanto a
página ancora em `date.today()`. Com um JSONL de quatro dias, o ritmo semanal
apareceu com o fim de semana mais forte que o dia útil, o oposto do que a
coleta do dia mostrava. Não deu erro, não pareceu errado: só estava. Hoje o
`placar.py` avisa quando o arquivo não é do dia.

**Deixar o viés voltar pela porta dos fundos.** A comparação de mentoria já
tinha sido consertada uma vez: buscar o perfil dos afilhados que não estão no
universo, senão a amostra é só de quem deu certo. Mas nada impedia a página de
voltar ao número enviesado se essa busca falhasse — ela publicaria "100% contra
12%" sem avisar que mediu doze de oitenta e oito. Correção errada é a que
depende de tudo dar certo. Hoje a página mede a cobertura e, abaixo de um piso,
não mostra a comparação: diz que a amostra é parcial e por quê.

**Achar que layout correto é página boa.** O auditor cobria transbordo,
contraste nunca tinha sido medido e desempenho, muito menos. Medindo: 21
combinações de cor e fundo abaixo do mínimo da WCAG AA nos dois temas, várias
perto de 2:1, quase todas por esmaecer texto com `opacity` — para passar, as
opacidades teriam que ir a 0,80–0,95, ou seja, a ferramenta estava errada e a
hierarquia tinha que vir de cor e tamanho. E num celular quatro vezes mais
lento, abrir a aba do histórico travava a página por 2,8 segundos, porque
2.624 linhas viram dezenas de milhares de nós. O gargalo não era montar a
string, que custa 72 ms: era o tamanho do DOM. Com teto de linhas, 91 ms.

Cuidado ao medir contraste por conta própria: o primeiro medidor que escrevi
acusou nome preto sobre fundo branco com 1,3:1, porque lia `color-mix` — que o
Chromium devolve como `color(srgb 0.93 …)`, de 0 a 1 — na mesma escala de
`rgb()`, de 0 a 255. Medidor errado é pior que nenhum.

**Ordenar "a caminho do próximo nível" pelo acumulado.** As duas listas do
painel nasceram assim: "mais perto de chegar" por `fracToNextRank`, "já
chegaram" por nível e edições de carreira. Acumulado é o que já foi feito, e o
que já foi feito não vence quando a pessoa parou. Medido em 06/08/2026: dos
doze de "mais perto de chegar", nove levariam mais de 730 dias para bater o
limiar no ritmo dos últimos 90 dias, e o primeiro colocado tinha 99% de
progresso com três edições na janela inteira. Quem chegaria em três semanas
não aparecia.
Foi um editor da comunidade que reclamou, citando dois nomes da lista que já
tinham largado o Waze; o número acima veio depois, para conferir a reclamação.
Hoje as duas listas ordenam por atividade — quem já chegou, pelas edições da
janela; quem falta, pelo que falta dividido pelo ritmo medido — e trocaram nove
dos doze nomes. É o mesmo erro que o placar inteiro existe para não cometer, e
foi cometido dentro dele. O `verificar.py` monta o painel com quatro
sintéticos em que as duas ordens são opostas e falha se a antiga voltar.

**Deixar o teto de linhas engolir a régua da mediana.** As duas réguas existem
porque só a média engana numa distribuição torta — está escrito mais abaixo, na
decisão que rejeitou marcar só a média. Só que a régua entra na posição onde o
valor cai, e a tabela desenha um pedaço por vez: no Histórico inteiro a mediana
cai na 1.462ª linha de 2.620, muito além das 300 desenhadas, então ela
simplesmente não aparecia. Sobrava a média — 23.648 contra uma mediana de 3 —,
exatamente a leitura que as duas réguas existem para evitar, na aba mais cheia
da página.

Passou porque cada peça estava certa sozinha: o valor batia, o teto era
proposital, e conferir "a régua mostra o número certo" não pergunta se ela
chegou a ser desenhada. Hoje a régua que cai além do corte encosta no fim do
que está na tela e diz em que posição fica de verdade. O auditor de DOM percorre
aba por estado — 100 combinações na coleta em que foi escrito — e falha se uma
régua com escopo suficiente não for desenhada.

Cuidado ao medir isto por fora: a lista de estados é remontada por aba, com só
os estados que têm gente nela. Pedir "AC" na aba de 7 dias põe o `select` em
"todos" sem reclamar, e a conferência passa a medir outra coisa — três falsos
positivos aqui antes de eu perceber.

**Deixar o número por extenso passar pela checagem de prosa.** A regra sempre
disse que "as três janelas" envelhece igual a "3 janelas", mas o conferidor só
procurava dígito. Escrevi "as duas janelas curtas" num painel novo e passou
liso. Hoje ele também procura a palavra. Ficam de fora "um" e "uma", que em
português são artigo antes de serem número e apitariam em cada frase.

Varrendo o `pagina.py` inteiro, só três textos visíveis tinham o problema — as
outras vinte e duas ocorrências eram comentário, que não envelhece na cara de
ninguém. Os três viraram frase sem número.

**Tratar busca e filtro de estado como a mesma coisa.** A coluna `#` vinha do
índice do que sobrava na tela, depois dos dois controles. Sem filtro, índice e
posição coincidem — e por isso passou por toda conferência, inclusive pelo
auditor de DOM, que comparava posição com índice, que é a mesma conta. Foi um
editor procurando o próprio nome que percebeu: 30º da aba, `#1` ao digitar
"antig".

Os dois controles não são a mesma coisa. **Estado troca o recorte**: filtrar a
Bahia é pedir o placar da Bahia, e ali ser o segundo é ser o segundo — renumerar
é o certo, e essa parte nunca esteve errada. **Busca procura dentro do recorte**
e não deveria mexer em nada além de esconder linhas.

A primeira correção errou a mão e tirou a renumeração dos dois, deixando a lista
de um estado com números salteados. O que o defeito pedia era separar os dois
casos, não unificá-los pelo outro lado.

As réguas tinham o mesmo emaranhado: recalculadas sobre tudo que estava na tela,
busca inclusive. Isso torna inútil justamente o uso principal — procurar o
próprio nome para se comparar com a média compararia a pessoa consigo mesma. Hoje
elas seguem o recorte, não a busca, e o rótulo diz de quem estão falando: "desta
aba" ou "de BA".

O auditor de DOM agora confere as duas regras separadamente, e com busca e
estado combinados.

**Deixar o ferramental fora do repositório.** Por dias os conferidores mais
pesados — a aritmética refeita do zero, o DOM contra o payload, o contraste
composto — moraram num diretório temporário de sessão. Rodavam, achavam
defeito, e sumiam com o contêiner: quem chegasse depois teria que reescrevê-los
para descobrir o que já se sabia. Hoje são `scripts/conferir.py`,
`scripts/auditar-dom.mjs` e `scripts/auditar-contraste.mjs`, e o
`verificar.py` recusa arquivo em `scripts/` que documento nenhum mencione —
ferramenta que ninguém sabe que existe é ferramenta perdida.

**Auditar layout com número de brinquedo.** O `auditar-layout.mjs` passava
porque a página de teste tinha KPI de cinco dígitos. Com o total real, de oito,
o cartão vazava em 390 e 768px. A auditoria só enxerga o que está na página que
você entrega a ela — teste com a ordem de grandeza real, que está na tabela
mais abaixo.

Voltou a acontecer em 24/10/2026, no painel "Chegaram na janela": nome real de
estreante é um token só e comprido, empurrava a tabela para fora do card, e a
página rolava de lado no celular. Os nomes sintéticos são curtos e não pegavam.
O que pegou foi rodar o auditor contra a página do ar, com dado real. O conserto
foi deixar o nome quebrar, como a tabela principal já fazia.

---

## Caminhos testados e descartados

**Escala dos mapas: gradiente contínuo em vez de baldes fixos.** Os dois mapas
de grade — cobertura de gerentes e onde se edita — usavam quatro baldes com
teto ("5+", "8+"). Medido: os gerentes por célula vão de 1 a 35 (mediana 5) e as
edições de 1 a 66 (mediana 2), então o balde de topo engolia mais da metade das
células num tom só. Hoje a escala é contínua, com o topo ancorado no máximo
daquela coleta — dinâmico — e curva de raiz, porque as duas distribuições
concentram no meio e o linear apagaria a mediana.

**Paleta dos mapas: arco-íris térmico (jet), escolhido com ressalva.** O padrão
seguro para magnitude é uma cor só, claro→escuro; o arco-íris (azul→verde→
amarelo→vermelho) é anti-padrão conhecido — cria faixas aparentes nas trocas de
matiz que não existem no dado, é o pior caso para daltônicos, e o vermelho
colide com o significado de sanção que a página usa em "fator 1". Foram
renderizados quatro mockups (azul por opacidade, azul aprofundado, quente de
matiz único, jet) e a escolha foi o jet, ciente disso. Um ganho real
compensou em parte: por usar cor sólida e não opacidade, o mapa lê igual no
tema claro e no escuro — a versão por opacidade serrilhava as bordas sobre
fundo escuro. Se um dia a legibilidade por daltônico pesar mais que a estética,
o caminho de volta é o azul aprofundado, também já medido e pronto no histórico.

**Contorno das UFs no mapa de cobertura, e a cor que ele tem que ter.** As
células ficavam soltas no vazio, sem referência de onde no país caem. Entrou um
contorno das UFs, estático e simplificado do polígono do IBGE, no sistema de
coordenadas da própria grade — casa com as células por construção, sem projeção
intermediária. Vai por cima das células, não por baixo: a cobertura preenche
quase o país inteiro e enterraria um traço embaixo.

A cor foi o que deu trabalho. **Branco puro não serve**: lê muito bem no tema
escuro, e no claro some — sobre o fundo da página nas regiões sem célula, e
sobre as células amarelas da parte de cima da rampa. Foi assim que a primeira
versão foi parar no ar e voltar. Duas saídas foram desenhadas e descartadas: o
**halo** (traço escuro largo por baixo, branco fino por cima) resolve em
qualquer fundo, mas engrossa a ponto de competir com o dado, e no tema escuro
deixa uma borda suja em volta das áreas vazias; o **cinza médio único** nos dois
temas é o mais simples, e nunca tem contraste máximo em nenhum dos dois. Ficou a
cor por tema, na variável `--contorno` — escura no claro, branca no escuro —,
que é como o resto da página já resolve `--grid` e `--baseline`.

Antes disso tudo cogitou-se puxar os **azulejos do livemap do Waze** por baixo.
Três motivos derrubaram: o livemap é Web Mercator e a grade é equirretangular,
então os azulejos entrariam tortos em relação às células, cada vez mais para o
sul; buscar azulejo é requisição para fora, e "a página não fala com ninguém" é
invariante conferido; e raster pesado brigaria com o desenho por cima.

**Snapshot e diff de `ALL_TIME`.** Funcionava e resolvia qualquer janela, não
só as três da API. Removido quando o escopo passou a ser "sem armazenamento".
Continua sendo a melhor saída se um dia houver onde guardar — o código está no
histórico do git, antes do commit que reduziu o escopo para o Brasil.

**Painel de "quem voltou a editar".** Implementado e medido. Na coleta em que
foi avaliado deu zero retornos, e a decisão foi não dar painel próprio a um
número desses — hoje ele aparece como frase dentro da vigília. Fica o registro
de que a justificativa envelheceu: em 03/08/2026 foram 7. Se passar a ser
rotina, vale reabrir.

**Distância até os colegas de estado sem recortar o Brasil.** A primeira versão
misturava "cuida de outro estado" com "cuida de outro país", e o primeiro
colocado aparecia a 6.081 km. Recorta-se o Brasil antes de medir.

**Paginar `Transactions` com `nextTransactionDate`.** Parece cursor, não é:
reenviar devolve a mesma página. Verificado comparando os `daysSince`.

**Comparar a composição de tipos recente com a histórica.** As taxonomias são
diferentes — `Node`, `PermanentHazard` e `Street` não existem no `editsByType`.
A comparação não é válida e a frase que a afirmava saiu.

**Fuso de Brasília na página.** Decidido manter UTC, que é o fuso do servidor.

**Marcar só a média na tabela.** A ideia era uma linha de média para se comparar
com ela. Medindo antes de implementar, a média cai no terço superior de toda
aba, porque a distribuição é muito torta: no Histórico ela é 5.946 vezes a
mediana e deixa 91% da lista "abaixo da média" — verdade aritmética que não
informa nada e, numa página de comunidade, só desanima. Entraram as duas
réguas: a mediana parte a lista ao meio, que é onde a pergunta "sou típico?" se
responde, e a distância até a média mostra a concentração sem precisar dizer.

**Painel de "onde se edita sem gerente ativo".** Era a ideia mais forte entre as
que não custam requisição: cruzar o mapa de atividade com o de cobertura e
apontar onde se edita sem ninguém responsável. Medido na coleta de 21/10/2026
antes de construir: das 354 células com edição recente, nenhuma estava sem
gerente ativo, e nenhuma dependia de um só — 64% das edições recentes caíram
onde 10 ou mais gerentes ativos se sobrepõem. O painel mostraria zero toda vez,
e a variante "onde a edição depende de um único gerente" deu o mesmo zero. Onde
se edita, a cobertura é redundante. Se houver fragilidade, ela está no que esta
fonte não vê: a área de quem parou de editar só aparece coletando as áreas dos
inativos, que é o item "áreas órfãs" em "Não explorado".

---

## Ordens de grandeza

Referência de uma execução saudável em 03/08/2026. Servem de canário: se a
próxima divergir muito de alguma, provavelmente quebrou coleta, não mudou o
Brasil.

| | |
|---|---|
| Universo | 2.534 editores |
| Ativos em 90 / 30 dias | 291 / 200 |
| Edições em 90 dias | 1.690.773 |
| Concentração no top 50 | 81% |
| Estados com fator de ônibus 1 | 20 de 27 |
| Ativos por nível, N1→N6 | 6%, 21%, 53%, 93%, 91%, 100% |
| Mentores / afilhados nomeados | 23 / 105 |
| Ativos: apadrinhados / demais | 36% / 11% |
| Estreantes na janela | 84, dos quais 20 ainda ativos |
| Cobertura de área | 127 editores, 515 áreas, 4.063 células |
| Edições recentes mapeadas | 1.642 de 251 editores |
| Retenção mediana das safras maduras | 18%, entre 14% e 26% |
| Ativos fora da varredura `ALL_TIME` | 42% |
| Linhas de ranking de janela sem edição | 99% |

Uma segunda execução completa, em 07/08/2026, para comparar: 2.618 editores no
universo, 304 e 218 ativos em 90 e 30 dias, 1.694.783 edições na janela, 81% no
top 50, 19 estados com fator de ônibus 1, 105 afilhados nomeados e todos
olhados, 133 editores cobrindo 552 áreas. Quatro dias depois da primeira e tudo
na mesma ordem de grandeza — que é o que a tabela existe para mostrar.

O `rankCandidates` entrou depois desta tabela, então ele tem os números dele, de
06/08/2026: **120 candidatos brasileiros na lista** e **90 que não apareciam em
ranking nenhum**. O total de omitidos por sanção fica aqui, não na página. Como esses 90
passaram a entrar no universo, o total de editores da próxima execução completa
vai nascer acima dos 2.534 desta tabela — a diferença é o endpoint novo, não
coleta quebrada.

O gradiente de nível é o melhor sinal de sanidade: a fatia ativa cresce forte
do N1 ao N4 — de 6% a 93% — e o N6 fica em 100%. **Não é monótono**: nesta
medição o N5 aparece abaixo do N4, 91% contra 93%. A diferença é de dois
editores e não significa nada; o que importa é o formato geral.

Isso aqui já se contradisse: o parágrafo dizia "sobe monotonicamente" com a
tabela logo acima mostrando 93% e depois 91%. E a página repetia a mesma
afirmação em prosa, escrita à mão. Hoje a página mede e diz onde quebra, e este
parágrafo descreve o que a tabela realmente mostra.

Se o gradiente perder o formato — N1 alto, N6 baixo, ou saltos grandes no meio
—, desconfie da coleta antes de desconfiar da comunidade.

---

## Conferido, e não é problema

Coisas que dariam um bom susto se estivessem erradas e por isso foram medidas.
Estão aqui para ninguém gastar o tempo de novo — e para saber o que refazer se
o código mudar.

**Nome de editor não injeta HTML.** Nome, cidade e tipo de objeto vêm da API e
são escolhidos por quem se cadastra. Montando a página com nomes como
`<img src=x onerror=…>` e `</script><script>…`, nada executa: tudo sai como
texto literal, o link vai percent-encoded, e a página não ganha nenhuma tag
`img` ou `script` a mais. Se algum trecho novo montar HTML sem passar pelo
`esc()`, refaça este teste.

**A página não fala com ninguém.** Nenhuma requisição sai para fora ao abrir,
trocar de aba, filtrar ou trocar de tema: nada de fonte remota, analytics ou
CDN. Só fontes de sistema. Vale conferir de novo se alguém adicionar biblioteca.

Isso vale para o arquivo que o `placar.py` gera, não necessariamente para o que
o domínio serve. Em 24/10/2026 o domínio estava atrás da Cloudflare com o Rocket
Loader ligado: ele troca o `type` dos scripts da página por um que o navegador
não executa e só os roda pelo script dele, injetado no fim. Sem esse script a
página fica vazia — sem KPIs, tabela nem painéis —, o que foi reproduzido
abrindo a página do ar como arquivo local. Quem bloquear o script da Cloudflare
vê a página em branco, e o script que evita o piscar de tema, que precisa rodar
antes da pintura, fica preso até o carregador do fim. Conferir o arquivo não
basta: confira também o que o domínio entrega.

**Teclado e leitor de tela.** A ordem do Tab é a visual, todo controle tem foco
visível e nome acessível, e Enter aciona abas e o botão de tema.

**Nenhum número da prosa está escrito à mão.** A pergunta veio de fora: de onde
sai o "só nomeia a cidade em N% das edições"? Sai de `city` vindo em cada
transação, contado contra o total da janela — 1.402 de 2.021 na coleta
conferida, e o número acompanha quando a entrada muda. Para o caso geral, duas
páginas foram geradas de coletas diferentes e toda a prosa que um leitor vê
— legenda, dica de hover, `title=` de coluna, rótulo de aba, 433 e 401 frases
— foi comparada trocando cada número por um buraco. Das 109 frases com número
idêntico nas duas, cerca de metade era dígito dentro de nome de usuário, o
resto era constante nomeada viajando no `cfg` ou dado que coincidiu por eu ter
alimentado as duas com o mesmo `areas.json`. Sobraram duas frases sem
explicação — o `foraPct` e o `semEdicaoPct` —, e variar os dois mudou o texto.

Esse comparador **não** virou ferramenta: precisa de duas coletas e devolve
cem linhas para triar à mão, enquanto o `verificar.py` pega a mesma classe de
defeito no código-fonte, sem ambiguidade. Conferido escrevendo `69%` à mão na
frase da cidade: os dois checadores de prosa acusaram na hora.

---

## Não explorado

**Áreas de editores inativos.** Hoje só os ativos têm `Areas` coletada, então o
mapa mostra onde há gerente presente. Coletando dos inativos daria para achar
**área órfã** — região cujo gerente sumiu —, que é acionável para um Champ.
Custo: até 2.500 requisições a mais.

**`Transactions` dos inativos**, pelo mesmo motivo e com o mesmo custo. Menos
interessante: para quem parou, as dez últimas edições são antigas.

**Outros países.** Toda a estrutura é agnóstica menos a lista de UFs, o mapa
`ESTADOS` e o recorte do mapa. Um país novo precisa das subdivisões em ISO
3166-2, dos nomes de estado por extenso como o `rankCandidates` os escreve, e de
uma caixa geográfica.

**Os outros dois ambientes `-live`.** `Descartes-live` e `il-Descartes-live`
respondem e trazem candidatos, mas nenhum brasileiro. Só seriam úteis se o
escopo saísse do Brasil.

**Rate limiting.** Nunca foi testado o teto, de propósito. Se um dia for
necessário subir o ritmo, subir aos poucos e observar, não procurar o limite.
