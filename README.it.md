# Innova Cloud per Home Assistant

Integrazione per i **climatizzatori e fan coil Innova di nuova generazione** (unità 2024 in poi,
serie FÄRNA e 2.0 con modulo Wi‑Fi ESP32) che si comandano solo con l'**app "Innova" di Solution Tech**
e **non hanno un'API locale**.

Le Innova 2.0 e AirLeaf più vecchie, quelle che rispondono su `http://<ip>/api/v/1/status`, sono
coperte da [danielrivard/homeassistant-innova](https://github.com/danielrivard/homeassistant-innova):
se la tua unità risponde a quell'indirizzo usa quella, se funziona solo tramite cloud e pairing
Bluetooth usa questa.
[ChristophHohner/homeassistant-innova-duepuntozero](https://github.com/ChristophHohner/homeassistant-innova-duepuntozero)
usa lo stesso cloud ma con gli endpoint **v1** (`api.innova.solutiontech.tech`, `grpc.innova.solutiontech.tech`)
che l'app attuale non usa più; questa integrazione implementa la API v2 (`v2.api…` / `v2.grpc…`,
servizio `services.app.AppService`) richiesta da firmware e app attuali. Anche
[buenaonda/innova-farna-ha](https://github.com/buenaonda/innova-farna-ha) usa la API v2, in polling
su `get_state`; questa integrazione in più tiene aperto il flusso eventi (le modifiche compaiono
entro un secondo), rinnova la sessione da sola, espone gli interruttori silenziosa / ricambio aria /
forzatura manuale e documenta l'intero protocollo con gli strumenti usati per ricostruirlo.

## Perché esiste (una nota per Innova)

Diciamolo chiaramente: è indecente che un climatizzatore di questa fascia di prezzo arrivi senza
un'API documentata, senza un'interfaccia locale e senza integrazione con Home Assistant, Alexa o
HomeKit, e che l'unico modo per comandarlo sia un'app chiusa che passa solo dal cloud. Un
proprietario non dovrebbe dover fare il reverse engineering di un'app per accendere il proprio
condizionatore. Ma questa è la situazione, e per questo esiste questa integrazione.

Verrà mantenuta. Se le prossime versioni dell'app o del firmware cambieranno il protocollo o
proveranno a chiudere il controllo dietro gateway proprietari, il protocollo verrà ricostruito di
nuovo e l'integrazione aggiornata. A Innova e Solution Tech: la strada migliore è pubblicare l'API.
La porta è aperta, e questo repository documenta già gran parte di quello che servirebbe.

## Come funziona

L'app parla con `v2.api.innova.solutiontech.tech` (REST) e `v2.grpc.innova.solutiontech.tech`
(gRPC con protobuf). Il protocollo è stato ricostruito dal binario dell'app, vedi
[docs/PROTOCOL.md](docs/PROTOCOL.md) e [proto/innova_app.proto](proto/innova_app.proto).
L'integrazione legge case, stanze e dispositivi dalla REST, chiede lo stato completo di ogni unità,
tiene aperto un **flusso di eventi gRPC** (le modifiche fatte da app, telecomando o pannello arrivano
in Home Assistant entro un secondo) e invia i comandi con `SendDevice`.

## Come potrebbero bloccarla, e cosa la protegge

L'integrazione dipende da un cloud controllato dal produttore. Con onestà sui modi in cui può rompersi:

| Potrebbero… | Probabilità | Cosa c'è in campo |
| --- | --- | --- |
| Cambiare protocollo con una nuova app o firmware | alta, nel tempo | `tools/` ricostruisce lo schema dal binario dell'app in minuti; un workflow giornaliero apre una issue quando esce una nuova versione sull'App Store; il codec ignora i campi sconosciuti |
| Riconoscere i client non-app (user agent, header, TLS) | media | REST e gRPC usano gli stessi identificativi dell'app; il ritmo di richieste è molto sotto quello dell'app |
| Togliere il login email/password (solo Google/Apple) | media | Resta la via del token di sessione (dura un anno); si può aggiungere il flusso Google |
| Richiedere l'attestazione del dispositivo (Firebase App Check / App Attest) | medio-bassa, è l'unico blocco vero | Nessuna via pulita; il ripiego è un token passato da un dispositivo reale. Ed è il punto in cui entra in gioco il Data Act europeo (sotto) |
| Sospendere gli account che usano client di terze parti | bassa | Il comportamento ricalca l'app; nessun abuso del servizio |
| Chiudere funzioni dietro un gateway a pagamento ("Butler") | possibile | Il gateway parla lo stesso protocollo (è uno dei tipi di nodo dello schema) |

Il **Data Act europeo** (Regolamento 2023/2854, applicabile dal 12 settembre 2025) dà a chi usa un
prodotto connesso il diritto di accedere ai dati che il prodotto genera e di condividerli con terzi,
e impone che i prodotti siano progettati perché i dati siano accessibili. Un produttore che blocca
attivamente l'accesso del proprietario alla propria unità sta dalla parte sbagliata. Per la cronaca: ho la
pettiness, il tempo e i soldi per farne un caso d'esempio.

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

## Altri marchi (app white-label)

Il cloud Innova è rivenduto ad altri marchi: Panasonic **Aquarea Home**, **DiffusApp** (STG / Diffusalp),
**Rhoss Tema** ed **Etherma Fire+Ice 2** usano la stessa piattaforma su un proprio tenant
(`v2.api.<marchio>.solutiontech.tech`). Scegli il marchio nel primo passo della configurazione; per un
tenant non in elenco scegli *Host personalizzati*. Lo schema dei messaggi è lo stesso per tutti.

## Opzioni

*Impostazioni → Dispositivi e servizi → Innova Cloud → Configura*: intervallo della rilettura completa
dello stato (10 minuti di default). Le modifiche in tempo reale arrivano comunque dal flusso eventi.

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

## Robustezza

Cosa succede quando un'unità perde il Wi‑Fi, il cloud si riavvia, il token scade o aggiungi/togli un'unità nell'app è documentato scenario per scenario in [docs/ROBUSTNESS.md](docs/ROBUSTNESS.md) (in inglese).

## Log di debug

```yaml
logger:
  logs:
    custom_components.innova_cloud: debug
```

Progetto indipendente, non affiliato a Innova o Solution Tech. Licenza MIT.
