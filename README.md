# Bluetooth HUD

Painel local de telemetria Bluetooth para Linux, construído sobre BlueZ via D-Bus, FastAPI e WebSocket.

O objetivo é transformar um dispositivo Bluetooth previamente autorizado em uma fonte de telemetria em tempo real para uma interface local futurista: conexão, RSSI, bateria e estado do player, sem depender de polling agressivo via `bluetoothctl`.

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

Para outro dispositivo:

```bash
BLUETOOTH_DEVICE="AA:BB:CC:DD:EE:FF" bash scripts/run.sh
```

## Arquitetura

```text
Dispositivo Bluetooth
       │
       ▼
     BlueZ
       │ D-Bus signals
       ▼
 BlueZMonitor
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

O D-Bus é a fonte principal de eventos. Um snapshot lento é usado apenas para reconciliação de estado.

## Endpoints

- `GET /` — HUD local
- `GET /api/state` — snapshot JSON
- `GET /api/health` — saúde do monitor
- `WS /ws` — telemetria em tempo real

## Próximas etapas

- controles AVRCP: play/pause/next/previous;
- envio de arquivos via OBEX;
- histórico e tendência de RSSI;
- múltiplos dispositivos;
- modo "find my phone" com indicação de aproximação/afastamento;
- frontend mais avançado estilo HUD.

## Segurança

O projeto pressupõe dispositivos do próprio usuário já pareados/autorizados. Ele não tenta contornar autenticação, pareamento ou permissões do Android.
