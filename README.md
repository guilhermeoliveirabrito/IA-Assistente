# IA-Assistente

Um assistente pessoal de IA que roda no **seu próprio computador**, como um aplicativo com janela própria. Ele conversa com você, lê seus e-mails e agenda, entende PDFs, imagens e textos, controla o PC (abrir programas, tocar música, digitar e clicar) e trabalha em projetos **sozinho, em segundo plano**, enquanto você está fora, e você acompanha tudo pelo computador ou pelo celular.

Custo: **zero** (Gemini na camada gratuita, Gmail e Google Agenda, Spotify com a sua conta). Projeto open source em português, licença MIT.

> Seus dados ficam na sua máquina. Só os trechos necessários vão para a API do Gemini para a IA responder.

## O que ele faz

| Recurso | Como funciona |
|---|---|
| **App com janela própria** | Interface escura, respostas com tabelas, listas e código formatados, indicador de "pensando", voz opcional (falar em vez de digitar; ler respostas em voz alta) |
| **Medidor de consumo** | Mostra quanto da cota do dia você já usou, quanto resta e **quando renova** |
| **Arquivos e imagens** | Arraste ou cole imagens, PDFs, Word e arquivos de texto/código no chat |
| **E-mails** | Triagem a cada 15 min (importante / normal / newsletter / spam), resumo diário. Spam só vai para a lixeira com a sua aprovação (por padrão) e nunca é apagado para sempre |
| **Agenda** | Aponta conflitos, dias lotados e janelas livres (só leitura) |
| **Controle do PC** | Abre apps e sites, controla mídia, vê a tela, digita, clica. **Cada ação de risco pede a sua permissão** |
| **Spotify** | "Toque tal música" pela API oficial (precisa de Premium) |
| **Tarefas autônomas** | Você descreve um trabalho; ele faz um plano, cria o projeto numa pasta própria, escreve código, roda comandos e (se você permitir) envia ao GitHub. Orçamento por tarefa, pausa quando a cota acaba e **continua sozinho quando ela renova** |
| **Histórico** | Registro do que ele planejou e fez, que **se apaga sozinho** depois de alguns dias |
| **Memória editável** | Arquivos `.md` que você edita pelo app; entram em todas as respostas |
| **Celular** | Aprove pedidos e mande tarefas do iPhone (veja abaixo) |

Ainda não faz: WhatsApp (adiado de propósito; as opções não oficiais podem banir o número) e rodar com o computador desligado.

## Instalação

### 1. Python e dependências
Instale o Python 3.10+ e, na pasta do projeto:
```
python -m venv .venv
.venv\Scripts\activate          # Windows  (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

### 2. Chave do Gemini (grátis)
Crie uma chave em https://aistudio.google.com/apikey, copie `.env.example` para `.env` e cole lá.

### 3. Abrir o app
```
python app.py
```
No Windows, também dá para dar dois cliques em **Abrir Assistente.bat** (sem janela preta). Sem o `pywebview` o app abre no navegador.

Pronto: já dá para conversar, mandar arquivos e imagens e criar tarefas. O resto é opcional:

### 4. Gmail e Agenda (opcional)
1. Em https://console.cloud.google.com crie um projeto e ative a **Gmail API** e a **Google Calendar API**.
2. Em "Tela de consentimento OAuth": tipo **Externo** e, em "Usuários de teste", adicione o seu e-mail.
3. Em "Credenciais" crie um **ID do cliente OAuth** do tipo **App para computador**, baixe o JSON e salve como `credentials.json` na pasta do projeto.
4. Abra o app, vá em **Ajustes › Gmail e Agenda** e clique em **Conectar Google**. Autorize no navegador que abrir (o aviso de "app não verificado" é o seu próprio app: Avançado > continuar). Se preferir o terminal: `python main.py setup`.

Com o login feito, o app liga sozinho a rotina de e-mails e agenda em segundo plano, e você também pode pedir no chat ("resuma meus e-mails"). Para revisar o que a IA quer mandar para a lixeira: `python main.py aprovar`.

### 5. Spotify (opcional, precisa de Premium)
1. Em https://developer.spotify.com/dashboard crie um app.
2. Em "Redirect URIs" cadastre exatamente `http://127.0.0.1:8888/callback`.
3. Coloque o *Client ID* em `SPOTIFY_CLIENT_ID` no `.env` e reabra o app.
4. Em **Ajustes › Spotify**, clique em *Conectar* e autorize.

### 6. Projetos e GitHub (opcional)
Em **Ajustes › Projetos**, escolha a pasta onde ele cria os projetos e liste os repositórios (`usuario/repo`) em que ele **pode** enviar código. Fora dessa lista ele nunca faz push. O envio usa o `git` e as credenciais que já estão no seu computador.

## Como ele enxerga e controla o mouse

Para clicar, ele recebe uma foto da tela com uma **grade de números de 0 a 1000** (a escala em que o Gemini enxerga melhor, independente da resolução e do zoom do Windows), mira no alvo e, depois de cada clique, tecla ou texto, recebe uma foto nova mostrando **onde clicou** (círculo vermelho). Para alvos pequenos ele amplia uma região antes de clicar. Sempre que dá, ele prefere atalhos de teclado e abrir programas e sites direto, que são mais confiáveis que clicar.

Enquanto usa tela, teclado e mouse ele **minimiza a janela do assistente** (para não digitar nela mesma) e a restaura ao terminar. Dá para desligar em Ajustes › Permissões. Se mover o mouse para um canto da tela, tudo é interrompido (trava de segurança do pyautogui), e o botão Parar do app também interrompe na hora.

## Como funcionam as tarefas autônomas

Em **Tarefas › Nova tarefa** você escolhe o que ele pode fazer sozinho:

- **Só leitura**: lê arquivos, e-mails e agenda, mexe na memória e na música.
- **Projeto**: também cria arquivos, roda comandos de desenvolvimento permitidos, abre apps e envia ao GitHub (só para os repositórios que você listou).
- **Controle total**: também usa tela, teclado e mouse (a janela do app se esconde enquanto isso).

(Com o modo autônomo ligado, que é o padrão, essa escolha some: ele já pode tudo isso.)

Por padrão o app roda em **modo autônomo**: ele usa o PC (abrir apps, tela, teclado, mouse, comandos) **sem pedir permissão** e você vê tudo depois no **Histórico**. Ele só para e pergunta se uma ação for **contra uma regra que você escreveu** em Memória › Regras (por exemplo, "nunca apague fotos"). Para voltar a ser perguntado a cada ação, desligue o modo autônomo em Ajustes › Permissões; aí valem os perfis acima, e ações de risco alto (comandos, tela/teclado/mouse, `git push`) pedem aprovação, no app ou por aviso no celular.

As travas técnicas continuam sempre ligadas, no modo autônomo também: comandos só rodam na pasta de projetos e só com programas da lista permitida, e o `git push` só vai para os repositórios que você listou. Elas bloqueiam em vez de perguntar. Cada tarefa tem um **orçamento de requisições** para não gastar a cota do dia inteira; ao acabar, ela pausa e espera você liberar mais.

### E se a cota gratuita acabar?
- O app tenta primeiro os **modelos reserva** (a cota gratuita é separada por modelo).
- Se todos acabarem, as tarefas **pausam** (nada se perde) e **retomam sozinhas** logo depois da renovação diária (por padrão, meia-noite no horário do Pacífico; o app mostra a hora no seu fuso).
- O chat avisa que a cota acabou e quando volta. Se o Google der só um limite por minuto, o app espera alguns segundos e tenta de novo.

**Expectativa honesta:** o plano gratuito dá conta de **uma tarefa de cada vez**, de tamanho pequeno a médio (um site simples, um script, organizar arquivos, pesquisar e resumir). Trabalho longo de programação, com muitas idas e vindas, consome a cota do dia rápido e termina em vários dias. Vários agentes trabalhando em paralelo ("empresa de agentes") **não cabem** no plano gratuito. Os limites do Google mudam; confira os seus em https://aistudio.google.com/rate-limit e ajuste em **Ajustes › Limites da cota**. O medidor é uma estimativa feita pelo app, porque o Google não informa a cota restante.

## Usar pelo celular (iPhone)

O app é uma página servida pelo seu PC. Para o celular alcançá-la:

1. **Ajustes › Usar pelo celular** > ligue *Permitir acesso pela rede* e reabra o app. Ele mostra um **código de acesso** e os endereços.
2. No iPhone, na **mesma rede Wi-Fi**, abra o endereço no Safari. Depois: *Compartilhar › Adicionar à Tela de Início* e ele vira um ícone, como um app.
3. **Fora de casa**, instale o **Tailscale** (grátis) no PC e no iPhone e abra o endereço do Tailscale. É uma rede privada entre os seus aparelhos: não abra a porta do roteador para a internet.
4. **Avisos**: em **Ajustes › Avisos no celular** clique em *Ativar avisos*, instale o app gratuito **ntfy** no iPhone e assine o tópico mostrado. Você recebe um aviso quando ele precisar de aprovação, terminar, pausar ou falhar, e responde pelo app.

Observações: o computador precisa estar **ligado, com o app aberto e conectado à internet**. O microfone no iPhone só funciona com HTTPS (por exemplo, o endereço HTTPS do Tailscale); digitar funciona sempre.

## Memória e conversas longas

- A **memória** são arquivos de texto (`perfil.md`, `regras.md`, `notas.md` e outros) que você edita em **Memória**. O assistente também anota ali quando você pede "lembre que...".
- Conversas muito longas pesam e gastam cota. Por isso, quando uma conversa passa de um certo tamanho, o começo é **resumido automaticamente** e fica só o resumo mais as mensagens recentes. Imagens antigas saem do contexto.
- Em qualquer conversa, menu (⋮) › **Resumir e continuar** cria uma **conversa nova que começa de um resumo** da anterior, para recomeçar leve sem perder o fio.
- As tarefas também resumem o próprio andamento entre uma etapa e outra.

## Segurança

- O app só aceita conexões com o **código de acesso** (guardado em `data/access_token.txt`). No modo "local" só o próprio PC conecta; ainda há proteção contra sites maliciosos abertos no seu navegador e limite de tentativas erradas.
- `credentials.json`, `token.json`, `.env`, `data/` e `memory/` estão no `.gitignore` e **nunca** devem ser enviados ao Git.
- E-mails, arquivos e páginas lidos são tratados como **dados, nunca como ordens**, para reduzir o risco de alguém "mandar" o assistente fazer algo escondido num e-mail ou documento. Nenhuma defesa é perfeita; por isso o que é arriscado exige a sua aprovação.
- Comandos só rodam dentro da pasta de projetos, sem *shell*, com lista de programas permitidos. O `git push` só vai para repositórios que você listou.
- Quem tem o código de acesso controla o assistente. Trate-o como uma senha.

## Estrutura

```
app.py             abre o app (janela própria)
server.py          servidor local + API da interface (stdlib, sem framework)
web/               interface (HTML/CSS/JS puro, sem build)
agent.py           laço do agente (pensa, usa ferramentas, pede permissão)
agent_tools.py     ferramentas: arquivos, e-mail/agenda, PC, Spotify, projetos...
tasks.py           fila de tarefas autônomas (orçamento, pausa e retomada)
chatsvc.py         conversas, anexos, aprovações
context.py         resumo de conversas e limpeza de contexto
usage.py           medidor de consumo da cota
gemini.py / ai.py  cliente do Gemini (modelos reserva, tentativas)
permissions.py     o que pede permissão e o que não pede
workspace.py       pasta de projetos, comandos e git com travas
pc_control.py      abrir apps, tela, teclado, mouse
spotify_control.py Spotify (API oficial)
automation.py      rotina de e-mails e agenda em segundo plano
main.py            comandos de terminal (setup, triagem, memória...)
tests/             testes automáticos (não chamam Gemini nem Google)
```

## Testes
```
python -m unittest discover -s tests
node web/tests/md.test.js
```

## Roadmap
1. Rascunhos de resposta a e-mails com aprovação
2. WhatsApp com aprovação (via API oficial)
3. Vários agentes especializados (fora do plano gratuito, ou com uma chave paga)
