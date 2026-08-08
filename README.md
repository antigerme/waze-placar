# waze-placar

Ressuscitando o placar dos editores de mapa do Waze — Brasil.

O Waze aposentou o placar público dos editores, mas
`https://www.waze.com/leaderboard` só foi desvinculado da navegação: a página
ainda renderiza e a API por trás dela ainda serve dados. Este projeto lê essa
API ao vivo e remonta o placar que a comunidade perdeu.

Sem banco, sem servidor, sem estado. Um comando lê tudo do Waze e escreve um
HTML autocontido que abre em qualquer lugar.

## Uso

Precisa de Python 3.6+, nada além da biblioteca padrão — roda no
`/usr/bin/python3` de fábrica do RHEL 8, que ainda é o 3.6. A autenticação é o
cookie de sessão de uma conta logada no `waze.com`, em formato Netscape, por
padrão em `/tmp/cookies.txt`.

```bash
python3 scripts/placar.py                                   # gera placar.html
python3 scripts/placar.py --out /var/www/waze-placar/index.html
python3 scripts/placar.py --sem-areas                       # sem os dois mapas
python3 scripts/placar.py --sem-perfis                      # só o acumulado
python3 scripts/placar.py --perfis perfis.jsonl             # reusa uma coleta
python3 scripts/placar.py --salvar-perfis perfis.jsonl      # guarda para reusar
```

`scripts/perfis.py` faz a coleta de perfis sozinha, e é retomável — relendo o
JSONL, pula quem já foi. Serve para pesquisa e para preparar um `--perfis`.

## O que uma execução faz

| Etapa | Requisições | Em 03/08/2026 |
|---|---|---|
| Rankings: nacional + 27 UFs, nas três janelas | fixo | 84 |
| Lista nacional de novatos | fixo | 1 |
| Candidatos a subir de nível | fixo | 1 |
| Perfil de cada editor do universo | 1 por editor | ~2.500 |
| Lista completa de afilhados dos mentores | 1 por mentor | ~25 |
| Perfil dos afilhados que não estão no universo | 1 por afilhado | ~90 |
| Áreas gerenciadas dos ativos | 1 por ativo | ~290 |
| Últimas edições dos ativos | 1 por ativo | ~290 |

Só as três primeiras etapas têm tamanho fixo; as outras acompanham a comunidade,
então o total de hoje não é o de daqui a um ano. Na data acima deu cerca de
3.300 requisições em ~40 minutos, no ritmo de ~1,25 req/s que o coletor impõe.
`--sem-areas` corta as duas últimas etapas; `--sem-perfis` deixa só as três
primeiras — e aí a página sai só com o ranking acumulado, sem janelas nem
painéis, porque é só isso que essa coleta mede.

## O que a página mostra

Quatro abas — 30 dias, 7 dias, 90 dias e Histórico — ordenadas por edições
reais da janela. Cada linha traz UF, nível, selos de especialidade e ritmo,
faísca de 90 dias, sequência de dias consecutivos e tendência.

A tabela desenha um pedaço por vez, com um botão para soltar o resto. Não é
economia de dados: o histórico tem milhares de editores, cada linha vira mais
de dez nós, e montar tudo travava um celular modesto por quase três segundos a
cada troca de aba. A busca e o filtro de estado continuam procurando em todo
mundo.

Dentro da tabela, duas réguas marcam onde cai o editor típico e onde cai a
média da aba. São linhas de referência, não pessoas: sem posição, sem selo e
sem link. Acompanham o filtro de estado e a busca, e somem quando sobra pouca
gente na tela para o valor significar algo.

Em "A caminho do próximo nível" a ordem é atividade, não acumulado: quem já
bateu o limiar aparece por edições da janela, e quem ainda não, pelo prazo que
o ritmo da janela daria — o que falta dividido pela produção diária. Ordenado
por progresso, o painel punha no topo quem tinha 99% feito e havia parado.

Tema claro e escuro: sem escolha feita a página segue o sistema, e o botão no
canto superior fixa uma das duas. A escolha fica no `localStorage` do próprio
navegador — a página continua estática, sem servidor e sem estado do lado de
cá.

Abaixo da tabela, os painéis — `scripts/verificar.py` confere esta lista contra
os títulos que o `pagina.py` gera, para ela não descolar de novo:

<!-- paineis:inicio -->
- Estados e fator de ônibus
- Concentração
- Safras de entrada
- Produziam e pararam
- Gigantes parados
- Ritmo semanal
- Nível e atividade
- Chegaram na janela
- A caminho do próximo nível
- Mentoria
- Cuidam de longe
- Cidades mais editadas
- O que está sendo mexido
- Calendário de edições
- Onde se edita agora
- Cobertura de gerentes
<!-- paineis:fim -->

Nem todos aparecem sempre: os que dependem de áreas ou de edições recentes
somem com `--sem-areas`, e "Cuidam de longe" só aparece quando há alguém
gerenciando área distante dos colegas de estado. Numa coleta `--sem-perfis` não
há vetor diário, então nenhum deles tem o que medir e a página diz isso em vez
de mostrar painel zerado.

**Todo texto da página é derivado dos dados.** Não há número escrito à mão em
lugar nenhum que alguém leia — nem na prosa, nem nas dicas de hover, nem nos
`title=` das colunas, nem nos rótulos das abas. Cada limiar é uma constante
nomeada no topo do `pagina.py`, viaja no `cfg` e é interpolado no texto: um
valor, um lugar.

As afirmações ou descrevem o método ou são medidas na coleta, inclusive as que
falam do formato do dado. A página não diz que o gradiente de atividade por
nível sobe — ela confere se sobe e, se não subir, diz onde quebra.

Isso é proposital, e `scripts/verificar.py` cobra: a versão anterior afirmava
coisas que deixaram de ser verdade sem ninguém perceber.

## Rodando diariamente no cron

```cron
17 5 * * * /usr/bin/flock -n /tmp/waze-placar.lock /usr/bin/python3 /home/user/waze-placar/scripts/placar.py --out /var/www/waze-placar/index.html --quiet >> /var/log/waze-placar.log 2>&1
```

Caminhos absolutos porque o cron roda com um ambiente mínimo. O `flock -n` evita
dois processos ao mesmo tempo se uma execução travar. Antes de agendar, rode uma
vez na mão para confirmar cookie e permissão.

### O que o script garante sozinho

**Publicação atômica.** A página é escrita num temporário no mesmo diretório e
só então renomeada por cima. Ninguém pega HTML pela metade, e o temporário fica
ao lado do destino de propósito: um arquivo movido de `/tmp` carregaria o rótulo
SELinux de lá e o httpd responderia 403.

**Permissão explícita.** O arquivo sai `0644` mesmo se o cron rodar com umask
restritiva — senão o httpd leva 403 num arquivo que existe.

**Nada de página degradada.** Se algum ranking não responder depois das
tentativas, o script aborta com saída 1 e não escreve nada — a página do dia
anterior continua no ar. O mesmo se o backend de perfis recusar a sessão no
meio. Para publicar mesmo incompleto, `--allow-partial`.

### A sessão se renova sozinha

O Waze responde os perfis com `Set-Cookie` de `_web_session`: a sessão é
rolante. O script grava o cookie jar de volta ao terminar, então cada execução
parte da sessão que a anterior renovou. Verificado em três execuções seguidas,
com o token rotacionando e a seguinte autenticando com o que a anterior gravou.
A gravação é atômica e mantém modo `0600`.

O que **não** acontece: o prazo absoluto do cookie não se move — fica fixo na
data em que a sessão nasceu no navegador, cerca de 30 dias. O que a renovação
sustenta é o tempo ocioso do servidor, bem mais curto, que é o que fazia os
perfis passarem a responder 403 depois de algumas horas.

Quanto isso dura na prática **não foi medido ao longo de dias** — a verificação
acima foi de execuções seguidas, não de uma semana de cron. Se um dia amanhecer
com 401, o mais rápido é conferir antes de investigar:

```bash
python3 scripts/placar.py --conferir
```

Uma requisição, resposta em segundos. `--nao-salvar-cookies` desliga a
regravação.

**401 não quer dizer prazo vencido.** Medido: o `_web_session` pode ter validade
a um mês de distância e a sessão já não valer. Exportar de um navegador onde a
conta não está logada naquele momento produz um arquivo com a cara certa e um
token morto — foi o que aconteceu aqui, com um export de um navegador e outro,
lado a lado, um funcionando e o outro não. Também medido: sessões diferentes
coexistem, então entrar no site por outro navegador não derruba a do servidor,
e a rolagem do Descartes não invalida o token para o `/_user/api`.

Como o arquivo virou credencial que precisa sobreviver a reinício, vale tirá-lo
de `/tmp` — algo como `/etc/waze-placar/cookies.txt`, com `--cookies` apontando
para lá.

### O que depende de você

- **Cookies legíveis e graváveis pelo usuário do cron**, já que o script
  regrava o arquivo.
- **Não reexporte por cima durante uma execução.** A gravação acontece no fim e
  sobrescreveria a exportação nova com a sessão da execução em andamento.
- **Contexto SELinux do diretório**, se ele foi criado à mão:

  ```bash
  sudo semanage fcontext -a -t httpd_sys_content_t "/var/www/waze-placar(/.*)?"
  sudo restorecon -Rv /var/www/waze-placar
  ```

- **Rotação do log**, se `/var/log/waze-placar.log` incomodar com o tempo.

## Antes de mexer

[`docs/api-recon.md`](docs/api-recon.md) é a referência da API: cada endpoint
usado, os ambientes em que ele funciona, e principalmente as armadilhas — o
`lookbackPeriod` que aceita valor inválido e responde 200 com outra coisa, o
`Areas` que só funciona num dos ambientes, a lista de afilhados truncada em 10,
a paginação de transações que não pagina, o campo `level` que some, o
`fracToNextRank` cujo denominador muda de pessoa para pessoa acima do primeiro
nível, os backends expirando em ritmos diferentes. Cada uma custou uma conclusão
errada aqui antes de virar uma linha no documento.

O documento também marca o que **não** se coleta e por quê: além dos endpoints
de PII, os campos do `rankCandidates` que dizem se uma pessoa nomeada está
banida ou com o nível travado.

[`docs/decisoes.md`](docs/decisoes.md) guarda o resto: os erros que este
projeto já cometeu e como cada um foi descoberto, os caminhos testados e
descartados com o motivo, as ordens de grandeza de uma execução saudável — que
servem de canário — e o que ainda não foi explorado.

## Conferindo a página gerada

O `verificar.py` roda sozinho e é barato, mas só olha o código e a
documentação. Estas quatro ferramentas olham a página pronta, cada uma por um
ângulo que as outras não cobrem. Rode as quatro depois de mexer no `pagina.py`:

```bash
python3 scripts/conferir.py --pagina placar.html --perfis perfis.jsonl
node scripts/auditar-layout.mjs placar.html
node scripts/auditar-dom.mjs placar.html
node scripts/auditar-contraste.mjs placar.html
```

As três de navegador precisam de `npm i playwright`; `PLAYWRIGHT_CHROMIUM`
aponta um binário próprio, se houver.

**`conferir.py`** refaz a aritmética inteira a partir do JSONL cru e compara com
o `const D` que a página carrega — dezenas de milhares de conferências, uma por
valor publicado. Não chama as funções do `pagina.py` de propósito: reusá-las só
provaria que o código é igual a si mesmo. Precisa do JSONL da mesma coleta e do
dia de hoje, e recusa em vez de despejar mil falhas quando não é. Também recusa
uma página de `--sem-perfis`: sem vetor diário não há janela para conferir.

**`auditar-layout.mjs`** abre a página em quatro larguras e falha se algo rolar
lateralmente, vazar do painel, soltar erro de JS no console, mostrar número com
ponto decimal — que numa página em português é sempre defeito — ou desenhar uma
barra de tamanho diferente do que o CSS pediu.

**`auditar-dom.mjs`** compara o que o navegador realmente pinta com o payload
embutido, linha a linha, em cada aba e em três larguras. Payload certo não
garante página certa: o bug que travava toda barra num mesmo comprimento passou
por baixo de toda validação em Python.

**`auditar-contraste.mjs`** mede o contraste do texto pintado nos dois temas,
compondo as camadas — fundo semitransparente mesclado com o que está atrás,
opacidade herdada aplicada à cor. Sem compor, o medidor inventa falha: o
primeiro que escrevemos acusou nome preto sobre branco a 1,3:1.

Rode contra uma página com os números de verdade, não com dado de brinquedo: o
que estoura o layout é o total de oito dígitos, não o de cinco.

## Notas

- Cookies são credencial. O `.gitignore` bloqueia `cookies*.txt`, `*.har` e
  `.env`; melhor manter assim.
- O coletor usa throttle global com jitter entre requisições e embaralha a ordem
  dos editores. Não observei rate limiting, mas não testei o teto de propósito —
  a infraestrutura não é nossa.
- `/_user/api/user`, `/il-UsersProfile/app/userInfo` e `/_user/api/trip`
  devolvem PII real **do próprio chamador**. Nada dali entra no placar.
- Nenhum dado coletado é versionado. Cada execução refaz tudo do zero contra a
  API, e todo o conhecimento do projeto está no código e nos dois documentos.
