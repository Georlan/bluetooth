# Signal Deck · Bluetooth HUD

Painel local de telemetria Bluetooth para Linux, construído sobre BlueZ via D-Bus, FastAPI e WebSocket. O Signal Deck combina intensidade do sinal, presença na rede local, bateria e estado de mídia em uma interface responsiva e atualizada em tempo real.

O objetivo é transformar um dispositivo Bluetooth previamente autorizado em uma fonte de telemetria útil, sem polling agressivo via `bluetoothctl`. A indicação de proximidade é qualitativa: paredes, orientação da antena e interferências alteram o RSSI, então o painel não afirma uma distância física exata.

## O que o painel mostra

- proximidade qualitativa com filtro de mediana, suavização e histerese — sem inventar uma direção que o RSSI não mede;
- tendência de aproximação ou afastamento;
- histórico recente do RSSI reconstruído ao abrir a página;
- bateria, conexão, pareamento, confiança e mídia do dispositivo;
- confirmação independente de presença na mesma rede local;
- confiança combinada e frescor de cada sensor;
- reconexão automática do navegador e recuperação do monitor BlueZ;
- modo de demonstração sem hardware.

## Stack

- Linux + BlueZ
- Python 3.11+
- `dbus-next`
- FastAPI
- WebSocket
- frontend HTML/CSS/JS local, sem CDN obrigatória

## Dispositivo usado nos testes

O protótipo foi iniciado com um Samsung A17 previamente pareado:

```text
EC:B5:50:2E:16:9C
```

Você pode trocar o endereço com a variável `BLUETOOTH_DEVICE`.

## Instalação

```bash
git clone https://github.com/Georlan/bluetooth.git
cd bluetooth
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Confirme antes que o telefone esteja conhecido pelo BlueZ:

```bash
bluetoothctl info EC:B5:50:2E:16:9C
```

## Testes

Execute a descoberta a partir da pasta `tests`:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

## Execução

```bash
bash scripts/run.sh
```

Abra:

```text
http://127.0.0.1:8765
```

Para explorar a interface com telemetria simulada:

```text
http://127.0.0.1:8765/?demo=1
```

Para outro dispositivo:

```bash
BLUETOOTH_DEVICE="AA:BB:CC:DD:EE:FF" bash scripts/run.sh
```

### Configuração

| Variável | Padrão | Uso |
| --- | --- | --- |
| `BLUETOOTH_DEVICE` | endereço do protótipo | endereço MAC Bluetooth monitorado |
| `PHONE_LAN_IP` | descoberta automática | IP do telefone na rede local |
| `BLUETOOTH_HOST` | `127.0.0.1` | interface em que o painel escuta |
| `BLUETOOTH_PORT` | `8765` | porta HTTP local |
| `BLUETOOTH_FAST_RSSI_INTERVAL` | `0.25` | intervalo do leitor HCI, em segundos |
| `PHONE_LAN_INTERVAL` | `0.50` | intervalo da confirmação LAN, em segundos |

Sem `PHONE_LAN_IP`, o alvo só é escolhido automaticamente quando existe exatamente um vizinho de rede elegível. Isso evita atribuir silenciosamente outro aparelho ao telefone.

## Arquitetura

```text
Dispositivo Bluetooth
       │
       ▼
     BlueZ
       │ D-Bus signals
       ▼
 BlueZMonitor
       │                 LanMonitor
       │                     │
       └──────────┬──────────┘
                  │
                  ▼
 TelemetryState
       │ WebSocket
       ▼
    FastAPI
       │
       ▼
 Futuristic HUD
```

O D-Bus é a fonte principal de eventos. Um snapshot lento é usado apenas para reconciliação de estado. Quando disponível, `hcitool rssi` fornece amostras rápidas; controladores que retornam zero repetidamente são descartados e o monitor volta ao RSSI do D-Bus.

## Endpoints

- `GET /` — HUD local
- `GET /api/state` — snapshot JSON
- `GET /api/health` — saúde do monitor
- `WS /ws` — telemetria em tempo real

## Próximas etapas

- controles AVRCP: play/pause/next/previous;
- envio de arquivos via OBEX;
- múltiplos dispositivos;
- calibração de proximidade por dispositivo;
- persistência opcional do histórico.

## Segurança

O projeto pressupõe dispositivos do próprio usuário já pareados/autorizados. Ele não tenta contornar autenticação, pareamento ou permissões do Android. Por padrão, o servidor escuta apenas em `127.0.0.1`; ao mudar `BLUETOOTH_HOST`, proteja o acesso à rede porque a interface expõe identificadores e telemetria do aparelho.
