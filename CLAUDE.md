# Instruções para o Claude Code neste repositório

## Leia antes de começar

- `docs/api-recon.md` — como a API do Waze se comporta, com as armadilhas.
- `docs/decisoes.md` — o que já foi testado e descartado, os erros que este
  projeto cometeu, e as ordens de grandeza de uma execução saudável.

Consultar os dois evita refazer caminho andado. Boa parte do que parece ideia
nova já foi tentada e está lá com o motivo da rejeição.

## Como o trabalho entra

Todo trabalho vai para uma branch e vira PR — nada direto na `main`. O merge é
sempre **squash**, e a branch é apagada logo depois: o repositório tem
"Automatically delete head branches" ligado, então isso não depende de ninguém
lembrar.

A consequência importa: depois de um merge, o commit da branch e o da `main` têm
o mesmo conteúdo com hashes diferentes, e a branch remota não existe mais.
**Comece toda sessão recriando a branch a partir da `main`**, nunca continuando
de onde a anterior parou:

```bash
git fetch --prune origin main
git checkout -B <branch> origin/main
```

Continuar da branch velha depois de um squash faz o PR seguinte propor de novo o
que já entrou. Já aconteceu, e o conserto — mesclar a `main` para dentro — deixa
um commit de merge que o squash não precisava.

## Idioma

Português em tudo que é escrito: mensagens de commit, documentação, comentários
de código, textos da página. Nomes de função e variável também.

## Regras que não se negociam

**Nada de número escrito à mão em nenhum texto da página.** Vale para a prosa,
para as dicas de hover, para os `title=` das colunas e para os rótulos das
abas — tudo isso é texto que alguém lê. Limiares vêm das constantes nomeadas no
topo do `pagina.py`, viram campo do `cfg`, e o texto interpola de lá. Um valor,
um lugar. Isso já foi violado várias vezes; da última, "últimos 90 dias" e "45
anteriores" estavam escritos à mão em uma dúzia de dicas.

Número por extenso conta igual: "as três janelas" e "as dez últimas" são número
escrito à mão e envelhecem do mesmo jeito.

**Não afirme causa, nem forma.** Se a coleta mostra dois números lado a lado,
mostre os dois. Explicar por que um número é o que é quase sempre significa
sair do que foi medido — foi assim que a página passou a dizer que dias fora da
curva "costumam ser mutirão".

O mesmo vale para descrever o formato de um dado. A página afirmava que o
gradiente de atividade por nível "sobe sem exceção do nível 1 ao 6": verdade no
dia em que foi escrito, mentira no dia em que a coleta falhar num nível. Hoje
ela confere e diz onde quebra. Se você for escrever "sobe", "é raro", "quase
todos" — meça e deixe o script escrever a frase.

**Rode os quatro conferidores depois de mexer no `pagina.py`.** O
`verificar.py` roda sozinho, mas só olha código e documentação; a página pronta
é outra coisa. As três de navegador precisam de `npm i playwright`.

```bash
python3 scripts/conferir.py --pagina placar.html --perfis perfis.jsonl
node scripts/auditar-layout.mjs placar.html
node scripts/auditar-dom.mjs placar.html
node scripts/auditar-contraste.mjs placar.html
```

Cada um cobre um ângulo que os outros não veem, e cada um existe por um erro
que passou pelos demais — está no README qual foi. Validar por métrica em
Python deixou passar uma tabela que estourava o container em todas as larguras;
validar o payload deixou passar toda barra travada no mesmo comprimento.

**Não chame `AddMentee` nem `ArchiveMentee`.** Alteram estado no Waze.

**Não colete dos endpoints de PII.** `/_user/api/user`,
`/il-UsersProfile/app/userInfo` e `/_user/api/trip` devolvem dados pessoais de
quem roda o script — nome, e-mail, endereço, histórico de navegação. Nada dali
entra em dataset ou na página.

**Não publique status disciplinar de ninguém.** O `rankCandidates` devolve
`mapEditingBanned` e `rankLocked` para gente nomeada. Os dois são sanção — o
segundo confirmado por Champ da comunidade —, e o placar é uma página de
comunidade. Quem tem qualquer um dos dois sai da lista inteira, não
só do campo — esconder a marca não basta, porque estar numa lista de "prestes a
subir de nível" já diz algo sobre quem está impedido de subir. Nem a contagem
vai para o HTML: com o total do painel ao lado, ela entregaria a proporção de
sancionados da comunidade. A página só avisa que houve exclusão. Se aparecer
campo novo dessa natureza, o padrão é remover o registro, não mascarar o
campo — e não publicar quantos foram.

Coordenada por pessoa também não: onde o projeto mostra posição, ele rasteriza
numa grade de dezenas de quilômetros. É por isso que o `lastEditPoint` do
`rankCandidates` não é coletado.

**Não aumente o ritmo das requisições.** O throttle com jitter em ~1,25 req/s é
deliberado. O teto do Waze nunca foi testado, de propósito.

## A verificação é automática

`scripts/verificar.py` roda sozinho ao fim de cada resposta, por um hook em
`.claude/settings.json`. Ele falha e devolve o motivo quando a documentação
descola do código: flag citada no README que não existe mais, endpoint novo sem
entrada em `docs/api-recon.md`, número literal em qualquer texto da página,
painel que o README não lista, seção perdida do `docs/decisoes.md`, ou
ferramenta em `scripts/` que documento nenhum menciona.

Ele também monta a página inteira com dado sintético e confere que o
`placar.py` ainda acha os campos que lê, e que o painel de quem está subindo de
nível continua ordenado por atividade. Renomear campo do payload quebrava só no
fim de uma coleta de dezenas de minutos, com a página já publicada.

Se ele reclamar, **atualize o documento** — não relaxe a checagem. Cada uma
delas existe porque a coisa correspondente já desatualizou sem ninguém notar.

## Ao coletar

Uma execução completa é cara — dezenas de minutos e milhares de requisições, uma
por editor do universo. Para iterar sem recoletar:

```bash
python3 scripts/perfis.py --out perfis.jsonl      # retomável
python3 scripts/placar.py --perfis perfis.jsonl   # reusa
python3 scripts/placar.py --sem-areas             # sem os dois mapas
python3 scripts/placar.py --limit 20              # amostra
```

Guarde a coleta num JSONL e reuse. Recoletar o universo inteiro para testar
mudança de layout é desperdício.

**Só não publique de JSONL velho.** O vetor diário do perfil é ancorado no dia
em que foi buscado, e a página ancora no dia de hoje: reusando um arquivo de
ontem, o ritmo semanal e as datas do calendário saem deslocados, sem erro
nenhum e sem parecer errado. O `placar.py` avisa quando o arquivo não é de
hoje. Para layout serve; para publicar, recolete.

## Cuidado com os cookies

O script **grava** `/tmp/cookies.txt`, não só lê — é assim que a sessão se
renova sozinha. Não sobrescreva o arquivo enquanto uma execução roda.

## Ao interpretar dados

Duas perguntas antes de concluir qualquer coisa:

1. **A fonte conseguiria mostrar o contrário?** O universo vem dos rankings,
   que excluem quem tem poucos pontos. Concluir "não há novatos" a partir dele é
   erro de amostragem, não achado.
2. **Por que este registro está na amostra?** Se estar na amostra já exige ter
   dado certo, a taxa de sucesso vai dar perto de 100% e não significar nada.
