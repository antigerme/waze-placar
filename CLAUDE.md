# Instruções para o Claude Code neste repositório

## Leia antes de começar

- `docs/api-recon.md` — como a API do Waze se comporta, com as armadilhas.
- `docs/decisoes.md` — o que já foi testado e descartado, os erros que este
  projeto cometeu, e as ordens de grandeza de uma execução saudável.

Consultar os dois evita refazer caminho andado. Boa parte do que parece ideia
nova já foi tentada e está lá com o motivo da rejeição.

## Idioma

Português em tudo que é escrito: mensagens de commit, documentação, comentários
de código, textos da página. Nomes de função e variável também.

## Regras que não se negociam

**Nada de número escrito à mão na prosa da página.** Todo texto do
`placar.html` ou descreve o método ou reporta algo medido na coleta. Limiares
vêm das constantes nomeadas no topo do `pagina.py`, e o texto que os menciona
lê da mesma constante. Isso já foi violado três vezes e produziu página
afirmando coisas falsas.

**Não afirme causa.** Se a coleta mostra dois números lado a lado, mostre os
dois. Explicar por que um número é o que é quase sempre significa sair do que
foi medido — foi assim que a página passou a dizer que dias fora da curva
"costumam ser mutirão", coisa que ninguém verificou.

**Rode `scripts/auditar-layout.mjs` depois de mexer no `pagina.py`.** Precisa de
`npm i playwright`. Validar por métrica em Python já deixou passar uma tabela
que estourava o container em todas as larguras.

**Não chame `AddMentee` nem `ArchiveMentee`.** Alteram estado no Waze.

**Não colete dos endpoints de PII.** `/_user/api/user`,
`/il-UsersProfile/app/userInfo` e `/_user/api/trip` devolvem dados pessoais de
quem roda o script — nome, e-mail, endereço, histórico de navegação. Nada dali
entra em dataset ou na página.

**Não aumente o ritmo das requisições.** O throttle com jitter em ~1,25 req/s é
deliberado. O teto do Waze nunca foi testado, de propósito.

## Ao coletar

Uma execução completa leva ~40 min e faz ~3.300 requisições. Para iterar sem
recoletar:

```bash
python3 scripts/perfis.py --out perfis.jsonl      # retomável
python3 scripts/placar.py --perfis perfis.jsonl   # reusa
python3 scripts/placar.py --sem-areas             # sem os dois mapas
python3 scripts/placar.py --limit 20              # amostra
```

Guarde a coleta num JSONL e reuse. Recoletar 2.500 perfis para testar mudança
de layout é desperdício.

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
