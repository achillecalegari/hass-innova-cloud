# Innova Cloud per Home Assistant

Integrazione per i **climatizzatori e fan coil Innova di nuova generazione** (unità 2024 in poi,
serie FÄRNA e 2.0 con modulo Wi‑Fi ESP32) che si comandano solo con l'**app "Innova" di Solution Tech**
e **non hanno un'API locale**.

Le Innova 2.0 e AirLeaf più vecchie, quelle che rispondono su `http://<ip>/api/v/1/status`, sono
coperte da [danielrivard/homeassistant-innova](https://github.com/danielrivard/homeassistant-innova):
se la tua unità risponde a quell'indirizzo usa quella, se funziona solo tramite cloud e pairing
Bluetooth usa questa.

## Come funziona

L'app parla con `v2.api.innova.solutiontech.tech` (REST) e `v2.grpc.innova.solutiontech.tech`
(gRPC con protobuf). Il protocollo è stato ricostruito dal binario dell'app, vedi
[docs/PROTOCOL.md](docs/PROTOCOL.md) e [proto/innova_app.proto](proto/innova_app.proto).
L'integrazione legge case, stanze e dispositivi dalla REST, chiede lo stato completo di ogni unità,
tiene aperto un **flusso di eventi gRPC** (le modifiche fatte da app, telecomando o pannello arrivano
in Home Assistant entro un secondo) e invia i comandi con `SendDevice`.

## Entità

* `climate`: spento / auto / caldo / freddo / deumidificazione / solo ventola, ventola auto / bassa /
  media / alta / boost (solo quelle che l'unità dichiara), temperatura con min/max/passo dell'unità,
  oscillazione flap, temperatura e umidità ambiente. Attributi: modalità operativa (programmazione /
  manuale / antigelo), preset del calendario attivo, modalità effettiva, bitmask allarmi.
* `sensor`: temperatura ambiente, umidità (se presente), modalità operativa, allarmi, segnale Wi‑Fi.
* `switch`: modalità silenziosa, ricambio aria (ERV, se presente), forzatura manuale (spegne la
  programmazione; con la programmazione attiva l'unità può annullare le modifiche alla fascia successiva).

Le pompe di calore vengono riconosciute ma per ora espongono solo sensori.

## Installazione con HACS

1. In HACS apri **Integrazioni → ⋮ → Repository personalizzati**.
2. Aggiungi `https://github.com/achillecalegari/hass-innova-cloud` con categoria **Integrazione**.
3. Cerca **Innova Cloud**, premi **Scarica** e **riavvia Home Assistant**.

In alternativa copia `custom_components/innova_cloud` in `<config>/custom_components/` e riavvia.

## Configurazione

**Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Innova Cloud**, poi scegli:

* **Email e password** dell'account dell'app. L'integrazione fa il login da sola e rinnova la
  sessione quando scade. Se l'account è stato creato con **Google** o **Apple**, imposta prima una
  password: nell'app scegli *Password dimenticata* con la stessa email, segui la mail e scegli una
  password (l'accesso Google/Apple continua a funzionare).
* **Token di sessione (avanzato)**: incolla il JWT usato dall'app. Dura circa un anno; alla scadenza
  Home Assistant chiede di autenticarsi di nuovo.

Viene creato un dispositivo per ogni unità, con il nome dell'app e la stanza come area suggerita.

## Ricavare il token (facoltativo)

Serve solo se non vuoi impostare una password. Il token è l'header `Authorization: Bearer …` che
l'app manda al cloud: lo mostra qualunque proxy HTTPS sul telefono, oppure su un Mac con l'app
iPad installata si trova nella cache dell'app:

```bash
sqlite3 ~/Library/Containers/tech.solutiontech.Innova/Data/Library/Caches/tech.solutiontech.Innova/Cache.db \
  "select request_key from cfurl_cache_response" | grep app/homes
```

e poi negli header della richiesta di quella voce di cache. Tienilo riservato: dà il controllo
completo delle unità.

## Test da riga di comando

`scripts/innova_cli.py` prova l'API senza Home Assistant (`pip install grpcio aiohttp`):

```bash
export INNOVA_TOKEN=eyJ...
python scripts/innova_cli.py homes
python scripts/innova_cli.py state AA:BB:CC:11:22:33
python scripts/innova_cli.py watch
python scripts/innova_cli.py set AA:BB:CC:11:22:33 --power on --mode cool --temp 24 --fan auto
```

Se qualcosa viene decodificato male, `python scripts/innova_cli.py raw <mac>` stampa la risposta
grezza: allegala a una issue su GitHub.

## Log di debug

```yaml
logger:
  logs:
    custom_components.innova_cloud: debug
```

Progetto indipendente, non affiliato a Innova o Solution Tech. Licenza MIT.
