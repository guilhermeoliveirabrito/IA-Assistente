# IA-Assistente

Assistente pessoal de IA que roda no **seu próprio computador**, sozinho e em segundo plano. Lê seus emails, separa o que é importante de verdade, analisa sua agenda, lê seus arquivos e **lembra das instruções que você der**. Custo: zero (Gmail API, Google Calendar API e Gemini na camada gratuita).

> Projeto open source em português. Seus dados ficam na sua máquina; só os trechos necessários são enviados à API do Gemini para a IA responder.

## O que ele faz

| Recurso | Como funciona |
|---|---|
| **Triagem de emails** | A cada 15 min classifica os emails novos em importante, normal, newsletter ou spam |
| **Resumo diário** | Às 08:00 resume o que realmente importa e o que pede resposta |
| **Spam seguro** | Por padrão só **sugere**; você aprova com `python main.py aprovar`. Vai para a lixeira (recuperável por 30 dias), nunca é apagado para sempre. Remetentes VIP nunca viram spam |
| **Análise da agenda** | Às 07:30 aponta conflitos, dias lotados e janelas livres, e sugere o que mover (só leitura, não altera nada) |
| **Memória editável** | Arquivos `.md` na pasta `memory/` que você edita como quiser; entram em todas as decisões da IA |
| **Leitura de arquivos** | Lê txt, md, csv, json, pdf e docx, **somente** nas pastas que você autorizar |
| **Modo conversa** | Chat no terminal com memória e arquivos anexados |

## O que ainda não faz

- WhatsApp
- Alterar a agenda ou responder emails sozinho
- Rodar com o computador desligado

## Instalação (uns 15 minutos)

### 1. Python e dependências
Instale o Python 3.10+ e, dentro da pasta do projeto:
```
pip install -r requirements.txt
```

### 2. Liberar acesso ao Gmail e à Agenda (Google Cloud, grátis)
1. Acesse https://console.cloud.google.com e crie um projeto (ex.: "assistente").
2. Em "APIs e serviços" > "Biblioteca", ative **Gmail API** e **Google Calendar API**.
3. Em "Tela de consentimento OAuth": tipo **Externo**, preencha o básico e, em "Usuários de teste", adicione o seu próprio email.
4. Em "Credenciais" > "Criar credenciais" > **ID do cliente OAuth** > tipo **App para computador**.
5. Baixe o JSON e salve na pasta do projeto com o nome `credentials.json`.
6. Rode `python main.py setup`. O navegador abre, você faz login e autoriza (pode aparecer um aviso de "app não verificado": é o seu próprio app, clique em Avançado > continuar).

> No modo "teste" o login do Google expira a cada 7 dias. Se isso incomodar, na tela de consentimento clique em "Publicar app" (continua só para você).

### 3. Chave do Gemini (grátis)
1. Crie uma chave em https://aistudio.google.com/apikey.
2. Copie `.env.example` para `.env` e cole a chave lá, **ou** defina a variável de ambiente `GEMINI_API_KEY`.

### 4. Pasta de arquivos (opcional)
Crie a pasta `~/assistente-arquivos` (ou outra) e coloque nela o que o assistente pode ler. Para usar outra pasta, edite `arquivos.pastas_permitidas` no `config.yaml`. Fora dessas pastas ele não lê nada.

### 5. Teste
```
python main.py triagem     # classifica emails agora
python main.py resumo      # resumo das últimas 24h
python main.py agenda      # análise da agenda
python main.py aprovar     # revisa o que a IA quer mandar para a lixeira
python main.py conversar   # conversa com memória e arquivos
```

### 6. Deixar rodando sozinho
```
python main.py rodar
```
Deixe o terminal aberto. Para iniciar junto com o computador:
- **Windows:** Agendador de Tarefas > "Ao fazer logon" > executar `python main.py rodar` na pasta do projeto.
- **Mac:** LaunchAgent.
- **Linux:** serviço `systemd`.

Resumos e análises também ficam salvos em `data/`.

## Memória: o assistente lembra de você

A memória são arquivos de texto na pasta `memory/`, criada na primeira execução a partir de `memory_example/`:

| Arquivo | Para quê |
|---|---|
| `perfil.md` | Quem você é, rotina, tom preferido |
| `regras.md` | O que ele deve sempre ou nunca fazer |
| `notas.md` | Instruções soltas que você pede para ele lembrar |

Qualquer outro `.md` que você colocar em `memory/` também entra (ex.: `projetos.md`). Você pode editar tudo na mão, em qualquer editor.

```
python main.py lembrar "reuniões só depois das 14h"   # grava uma nota
python main.py memoria                                # mostra tudo que ele sabe
python main.py esquecer 2                             # apaga a nota número 2
```

No modo conversa, basta escrever "lembre que ..." (ou "lembre-se de ...") para gravar. A memória vai para os prompts da triagem, do resumo, da agenda, da leitura de arquivos e da conversa. Quando fica grande demais, as notas mais antigas são cortadas e as recentes têm prioridade.

A pasta `memory/` está no `.gitignore`: **sua memória pessoal não vai para o GitHub**.

## Ler arquivos

```
python main.py arquivos                           # lista o que ele pode ler
python main.py ler contrato.pdf "qual o prazo?"   # pergunta sobre um arquivo
python main.py ler relatorio.docx                 # sem pergunta, ele resume
```

No modo conversa: `/anexar arquivo` coloca o arquivo no contexto, `/ler arquivo pergunta` faz uma pergunta pontual. PDFs escaneados (só imagem) ainda não são suportados.

## Configuração

Tudo em `config.yaml`: critérios de "importante", remetentes VIP, pastas de arquivos, horários, preferências de agenda, modelo do Gemini e modo de spam. Quando confiar na triagem, mude `email.spam.modo` para `automatico`.

## Segurança

- `credentials.json`, `token.json` e `.env` dão acesso à sua conta e à sua chave. Estão no `.gitignore`; **nunca** compartilhe nem force a inclusão no Git.
- O conteúdo de emails e arquivos é tratado como **dado, nunca como ordem**, para reduzir o risco de alguém "mandar" o assistente fazer algo por dentro de um email ou documento. Mesmo assim, nenhuma defesa contra esse tipo de ataque é perfeita, e por isso ações como apagar exigem sua aprovação por padrão.
- A leitura de arquivos bloqueia caminhos fora das pastas autorizadas, inclusive com `../` e atalhos (symlinks).
- Limite gratuito do Gemini: se estourar, a rodada falha e tenta de novo na próxima.

## Estrutura

```
main.py           comandos e agendador 24h
chat.py           modo conversa
memory.py         memória em arquivos .md
files.py          leitura segura de arquivos
triage.py         triagem de emails, resumo e fila de aprovação
agenda.py         análise da agenda
gmail_tools.py    leitura de emails e lixeira
google_auth.py    login no Google
ai.py             camada de IA (Gemini); para trocar de provedor, mexa só aqui
memory_example/   modelos da memória
tests/            testes automáticos
```

## Testes

```
python -m unittest discover -s tests -v
```

Os testes não chamam o Gemini nem o Google: usam uma IA falsa.

## Roadmap

1. Rascunhos de resposta para emails, com aprovação antes de enviar
2. WhatsApp com aprovação
3. Criar blocos de foco na agenda, com aprovação
4. Tarefas e projetos em segundo plano

## Licença

[MIT](LICENSE)
