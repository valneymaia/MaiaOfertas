# Maia Ofertas

Bot em Python para monitorar grupos de ofertas no Telegram, converter links para links de afiliado e repostar em um grupo destino.

O projeto foi feito para automatizar principalmente ofertas do Mercado Livre. Ele pega links recebidos em grupos, resolve encurtadores, tenta encontrar a URL real do produto, limpa rastreadores de afiliados de terceiros e gera um novo link pela API do Link Builder do Mercado Livre usando a conta configurada.

Tambem ha suporte basico para Amazon, aplicando a tag de afiliado configurada.

## Funcionalidades

- Monitora varios grupos/canais do Telegram com Telethon.
- Detecta links em mensagens recebidas.
- Remove blocos de divulgacao de grupos/canais antes de repostar.
- Resolve encurtadores como `meli.la` e `amzn.to`.
- Converte links do Mercado Livre para links de afiliado gerados pelo Link Builder.
- Converte links da Amazon trocando a tag antiga pela sua tag.
- Tenta enviar a imagem do produto junto com a legenda.
- Mantem o preview automatico do Mercado Livre desligado quando uma imagem propria e enviada.

## Fluxo Do Mercado Livre

```text
Mensagem recebida
-> Extrai URL
-> Resolve encurtador meli.la
-> Abre link do Mercado Livre com Playwright
-> Encontra a pagina real do produto
-> Limpa parametros de afiliado/rastreamento
-> Envia URL limpa para createLink
-> Recebe link afiliado oficial
-> Tenta pegar titulo/imagem do produto
-> Reposta no Telegram
```

O link final do Mercado Livre pode continuar parecido com:

```text
https://www.mercadolivre.com.br/social/seuusuario?...
```

Isso nao significa necessariamente erro. O importante e esse link ter sido gerado pela API do Mercado Livre a partir da URL limpa do produto.

## Limpeza De Mensagens

Antes de repostar, o bot remove blocos promocionais de outros grupos, como:

- `Todos nossos grupos`
- `Grupo de Ofertas`
- `Canal de Ofertas`
- links `t.me`
- links `linktr.ee`
- links de WhatsApp

Encurtadores genericos como `bit.ly`, `cutt.ly` e `tinyurl.com` sao resolvidos antes da conversao para afiliado. Se o destino nao for uma oferta suportada de Mercado Livre, Amazon, Shopee ou AliExpress, o link e removido do repost para nao criar botoes inuteis.

Quando algo e removido, aparece no log:

```text
[MSG] Links/blocos promocionais de grupos removidos.
```

## Imagem Do Produto

No Mercado Livre, o bot tenta abrir a pagina real do produto com Playwright e buscar a imagem principal no HTML da pagina, priorizando imagens com padrao de produto, como `D_NQ_NP` e `D_Q_NP`.

Logs importantes:

```text
[MLM] Seletor da imagem: ...
[MLM] Imagem principal via navegador: ...
```

Se aparecer:

```text
[MLM] Navegador nao encontrou imagem principal correta do produto.
```

significa que o bot evitou enviar uma imagem generica ou errada do Mercado Livre.

## Arquivo De Teste

O arquivo `ml_debug.py` serve para testar somente o fluxo do Mercado Livre, sem rodar o bot inteiro.

Use assim:

```powershell
& C:/Users/W10/AppData/Local/Microsoft/WindowsApps/python3.12.exe c:/Users/W10/Desktop/ofertas/files/ml_debug.py
```

Cole um link do Mercado Livre quando ele pedir. Ele mostra:

- URL recebida;
- URL real do produto;
- URL limpa;
- metadata encontrada;
- resposta da API do Mercado Livre;
- link afiliado final.

## Requisitos

- Python 3.10+
- Conta Telegram para Telethon
- Conta de afiliado Mercado Livre
- Playwright com Chromium instalado

Dependencias:

```text
telethon
httpx
python-dotenv
playwright
```

## Instalacao

```bash
pip install -r requirements.txt
playwright install chromium
```

## Configuracao

Crie um arquivo `.env` com base no `.env.example`.

### Telegram

Pegue `API_ID` e `API_HASH` em:

```text
https://my.telegram.org/apps
```

Exemplo:

```env
API_ID=123456
API_HASH=seu_hash
SOURCE_GROUPS=grupo1,grupo2,https://t.me/+convite
TARGET_GROUP=Maia Ofertas
```

### Mercado Livre

```env
ML_AFFILIATE_WORD=seuusuario
ML_CREATE_LINK_COOKIE=...
ML_CSRF_TOKEN=...
```

Para pegar `ML_CREATE_LINK_COOKIE` e `ML_CSRF_TOKEN`:

1. Entre no Mercado Livre logado.
2. Abra o Link Builder.
3. Abra o DevTools do navegador.
4. Va em `Network`.
5. Gere um link manualmente.
6. Clique na requisicao `createLink`.
7. Copie o `cookie` e o header `x-csrf-token`.

Esses valores podem expirar. Se o bot parar de gerar links ou retornar `401`/`403`, atualize no `.env`.

### Amazon

```env
AMAZON_AFFILIATE_TAG=suatag-20
```

## Como Rodar

```powershell
& C:/Users/W10/AppData/Local/Microsoft/WindowsApps/python3.12.exe c:/Users/W10/Desktop/ofertas/files/bot.py
```

Na primeira execucao, o Telethon pode pedir login da conta Telegram.

## Logs Uteis

```text
[URL] Link encontrado na mensagem
[RES] Link depois de resolver redirecionamento
[MLC] Conversao/limpeza de URL Mercado Livre
[MLB] Navegacao do Mercado Livre no browser
[MLM] Metadata/imagem do Mercado Livre
[ML ] Link afiliado Mercado Livre gerado
[AMZ] Link Amazon com tag aplicada
[+] Repostado
[+] Repostado com imagem do produto!
```

## Estrutura

```text
bot.py              Bot principal
config.py           Leitura das variaveis do .env
ml_debug.py         Teste isolado do Mercado Livre
requirements.txt    Dependencias Python
.env.example        Exemplo de configuracao
.gitignore          Arquivos ignorados no Git
README.md           Documentacao
```

## Seguranca

Nao suba estes arquivos para o GitHub:

- `.env`
- `affiliate_bot.session`
- `affiliate_bot.session-journal`
- `*.session`
- `*.session-journal`

Esses arquivos podem conter credenciais, cookies e sessoes autenticadas.

## Observacoes

- O Mercado Livre pode mudar pagina, seletores ou comportamento do Link Builder.
- Cookie e CSRF podem precisar ser atualizados periodicamente.
- Se a imagem do produto vier errada, teste primeiro com `ml_debug.py`.
- Se o link afiliado for gerado mas a imagem nao aparecer, o problema esta na captura/download da imagem, nao na API de afiliado.
