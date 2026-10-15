# AppDashboard

Ein schlankes, selbst gehostetes Dashboard für deine Anwendungen. Öffentlich sichtbare App-Kacheln mit Logo, Beschreibung und direktem Link; die Verwaltung ist durch einen Admin-Login geschützt. Komplett auf Deutsch, ohne externe Schriftarten, Tracking oder Favicon-Dienste.

## Was enthalten ist

- App per URL hinzufügen: Name, Beschreibung und Favicon werden automatisch vorgeschlagen. Bei neuen Einträgen beginnt der Abruf nach Verlassen des URL-Feldes; „Details laden“ startet ihn jederzeit erneut.
- Namen und Texte bearbeiten, eigene Logos hochladen, Kategorien vergeben und Einträge löschen.
- Reduzierte öffentliche Startseite unter `/`: Kompakte Kacheln mit Logo und Name sowie eine Suche. Ein Info-Button vergrößert eine Kachel und zeigt die vollständige Beschreibung, Kategorie und URL. Keine Seitenleiste, Statistiken oder Bearbeitungsbuttons.
- Separate Verwaltung unter `/admin` mit Kategorienfilter, Sortierung und Kachel- oder Listenansicht.
- In der Verwaltung persönliche Favoriten und Ansicht; helles/dunkles Design in beiden Ansichten im jeweiligen Browser. Standard ist „Automatisch“ entsprechend der Geräteeinstellung; Änderungen am Gerät werden sofort übernommen. Der Design-Button wechselt zwischen Automatisch, Hell und Dunkel. Favoriten sind nicht zwischen Geräten synchronisiert.
- SQLite-Datenbank und lokal gespeicherte Logos in einem Docker-Volume. **Eine zusätzliche MariaDB wird nicht benötigt.**
- Passwortgeschützte Schreibzugriffe, CSRF-Schutz, begrenzte Anmeldeversuche, sichere Sitzungscookies und eingeschränkter Metadatenabruf.
- JSON-Export für Admins und vollständige Datenbanksicherung per Skript.

Eine neue Installation enthält bewusst keine Beispiel-Apps. Die Nutzeransicht zeigt einen schlichten Leerzustand. In der Verwaltung hilft ein Assistent beim ersten Eintrag.

## Schnellstart mit Docker Compose

```bash
git clone https://github.com/phillipunzen/App-Dashboard.git AppDashboard
cd AppDashboard
cp .env.example .env
chmod 600 .env
```

In `.env` setzen:

```dotenv
ADMIN_USERNAME=admin
ADMIN_PASSWORD=ein-eigenes-langes-zufaelliges-passwort
PUBLIC_ORIGIN=https://apps.deine-domain.de
SECURE_COOKIE=true
TRUSTED_PROXY_HOPS=1
```

Anschließend starten:

```bash
docker compose pull
docker compose up -d
```

Der Dienst ist standardmäßig nur über `127.0.0.1:8080` auf dem Docker-Host erreichbar. Für einen anderen Port `PORT` in `.env` setzen. Den Admin-Benutzernamen und das selbst gewählte Passwort verwaltest du ausschließlich in der lokalen `.env` (Dateirechte `600`).

Deinen Reverseproxy auf `http://127.0.0.1:8080` bzw. den gewählten Port zeigen lassen. Die öffentliche HTTPS-Adresse zeigt die reduzierte Nutzeransicht mit App-Kacheln und Suche. Zur Administration **Verwaltung** im Seitenfuß öffnen oder direkt `/admin` aufrufen; dort links unten anmelden. Benutzername und Passwort entsprechen `.env`.

Für einen vorübergehenden Test ausschließlich über lokales HTTP: `SECURE_COOKIE=false`, `PUBLIC_ORIGIN=` leer lassen und den Container mit `docker compose up -d` neu erstellen. Für die öffentliche Bereitstellung wieder `SECURE_COOKIE=true` und die tatsächliche HTTPS-Adresse setzen. Ein HTTPS-Cookie wird beim Zugriff über eine normale HTTP-Adresse nicht übertragen.

## Docker-Image und automatische Builds

Die `docker-compose.yml` verwendet das fertige Image:

```yaml
image: ghcr.io/phillipunzen/appdashboard:latest
```

Image: [GitHub Container Registry](https://github.com/users/phillipunzen/packages/container/package/appdashboard). Unterstützt werden `linux/amd64` und `linux/arm64`.

Der [GitHub-Actions-Workflow](https://github.com/phillipunzen/App-Dashboard/actions/workflows/docker.yml) führt vor jeder Veröffentlichung die Backend- und Browserprüfungen aus, baut beide Architekturen, veröffentlicht die Images und prüft den gestarteten Container. Auf `main` wird `latest` aktualisiert; zusätzlich gibt es einen `sha-…`-Tag pro Commit. Git-Tags wie `v1.2.3` erzeugen die Image-Tags `1.2.3` und `1.2`. Pull Requests führen die Tests ohne Veröffentlichung aus. Die Authentifizierung für die Veröffentlichung erfolgt über den automatisch bereitgestellten `GITHUB_TOKEN`; zusätzliche Registry-Zugangsdaten sind im Repository nicht erforderlich.

GitHub legt neue Container-Pakete zunächst privat an. Für einen Download ohne Anmeldung das Paket einmalig unter **Package settings → Change visibility → Public** freigeben. Wenn es privat bleiben soll, vor `docker compose pull` mit `docker login ghcr.io -u phillipunzen` anmelden; als Passwort einen eigenen GitHub-Token mit `read:packages` verwenden. Siehe [GHCR-Dokumentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

Für eine feste Version `APPDASHBOARD_IMAGE` in `.env` anpassen. Updates laden und aktivieren:

```bash
docker compose pull
docker compose up -d
```

Ein lokaler Build ist weiterhin optional möglich:

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

Compose-Projekt, Service und Container heißen `appdashboard`. Die Daten liegen im Volume `appdashboard_data`. Image, Linux-Benutzer, Exporte und interne Bezeichnungen verwenden ebenfalls `appdashboard`. Der GitHub-Repository-Link bleibt die bestehende Adresse.

## Bestehende Installation auf die neuen Namen umstellen

Bei einer bestehenden Installation das bisherige Daten-Volume einmalig kopieren, bevor die neue Compose-Konfiguration gestartet wird. So werden Einträge, Logos und Sitzungsschlüssel übernommen. Die Quelle bleibt erhalten und eine bereits vorhandene Ziel-Datenbank wird nicht überschrieben.

1. Eine Datenbanksicherung erstellen und die Namen des bisherigen Containers und Volumes notieren (`docker ps`, `docker volume ls`).
2. Das neue Image laden: `docker pull ghcr.io/phillipunzen/appdashboard:latest`.
3. Den bisherigen Container stoppen: `docker stop <bisheriger-container>`.
4. Migration aus dem aktualisierten Repository starten:

```bash
python3 scripts/migrate_volume.py --source <bisheriges-daten-volume>
docker compose up -d
```

Danach unter `/` und `/admin` prüfen, ob die Einträge vorhanden sind. Erst nach erfolgreicher Prüfung den gestoppten bisherigen Container und sein Volume entfernen. Verwendet der Reverseproxy einen Docker-DNS-Namen, seinen Upstream auf `http://appdashboard:8080` anpassen. Die Portfreigabe auf dem Host bleibt unverändert. Eigene Compose-Overrides ebenfalls auf den Service `appdashboard` umstellen. Eine zuvor konfigurierte Image-Variable heißt jetzt `APPDASHBOARD_IMAGE`.

## Reverseproxy

Die Anwendung ist für eine eigene (Sub-)Domain im Wurzelpfad `/` ausgelegt. TLS endet am Reverseproxy; der Container selbst spricht HTTP auf Port 8080. WebSockets sind nicht nötig. Weiterzuleiten sind der ursprüngliche Host sowie `X-Forwarded-Proto` und `X-Forwarded-For`.

Beispiel Nginx (TLS-Zertifikate separat wie üblich konfigurieren):

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_read_timeout 45s;
}
```

Für Nginx Proxy Manager: Forward Hostname/IP = die vom Proxy erreichbare Docker-Host-IP, Forward Port = gewählter Host-Port, Scheme = `http`; SSL für die öffentliche Domain aktivieren. Eine an `127.0.0.1` gebundene Freigabe ist nur für einen Proxy direkt auf demselben Host erreichbar.

**Wenn dein Reverseproxy selbst in Docker läuft**, kannst du beide Dienste in ein gemeinsames Docker-Netz hängen. Der Upstream lautet dann `http://appdashboard:8080` und eine Portfreigabe ist nicht erforderlich. Beispiel einer lokalen `docker-compose.override.yml` (Netznamen ersetzen):

```yaml
services:
  appdashboard:
    networks:
      - proxy
networks:
  proxy:
    external: true
    name: dein-vorhandenes-proxy-netz
```

Damit ist der Dienst über den internen DNS-Namen `appdashboard` im gemeinsamen Netz erreichbar. Die bestehende Loopback-Portfreigabe kann bestehen bleiben. Bei einem Proxy auf einem anderen Rechner `BIND_ADDRESS` auf die interne Docker-Host-IP setzen und den Host-Port nur für diesen Proxy freigeben.

`TRUSTED_PROXY_HOPS=1` gilt für genau einen vertrauenswürdigen Proxy. Für direkten Zugriff ohne Proxy `0` setzen. Der Proxy muss eingehende Forwarded-Header selbst setzen bzw. bereinigen. `PUBLIC_ORIGIN` ist die öffentliche Adresse inklusive `https://`, ohne Pfad und ohne abschließenden Slash.

Die öffentliche Übersicht enthält alle gespeicherten URLs, Namen, Beschreibungen, Kategorien und Logos. Einträge sind entweder alle öffentlich lesbar oder die gesamte Website wird zusätzlich vom Reverseproxy geschützt. Die App führt keine eigene Anmeldung bei den verlinkten Anwendungen durch.

## Automatische Logos und Metadaten

Der Abruf erfolgt ausschließlich nach Admin-Anmeldung. AppDashboard liest den HTML-Titel, die Meta-Beschreibung und Icon-Verweise; danach versucht es `/favicon.ico`. Relative Icon-URLs und HTTP-Weiterleitungen werden unterstützt. Logos werden als kleine PNGs im Volume gespeichert und beim späteren Seitenbesuch von AppDashboard ausgeliefert. Besucher müssen daher keine externen Favicon-Dienste kontaktieren.

Nicht jede Anwendung stellt lesbare Metadaten bereit: Login-Schutz, reine JavaScript-Seiten, selbst signierte TLS-Zertifikate oder ausschließlich SVG-basierte Logos können den Abruf verhindern. Der Eintrag lässt sich trotzdem speichern; Name und Beschreibung können manuell eingegeben und PNG-, JPEG-, WebP-, GIF- oder ICO-Logos bis 250 KB hochgeladen werden. SVG-Dateien werden nicht übernommen. Fehlt ein Logo, erscheint ein farbiges Buchstaben-Icon.

Private IP-Adressen sind beim Abruf standardmäßig gesperrt. Für deine eigenen Anwendungen im LAN kann die Option eingeschaltet werden:

```dotenv
ALLOW_PRIVATE_METADATA=true
```

Damit werden RFC1918-Netze und IPv6-ULA freigegeben. Loopback, Link-Local und Cloud-Metadaten-Adressen bleiben gesperrt. Öffentliche und interne URLs können unabhängig davon als Links gespeichert werden; die Sperre betrifft nur den serverseitigen Abruf. Interne Namen müssen im Container auflösbar sein. Zertifikatsprüfung bleibt immer aktiv.

## Konfiguration

| Variable | Standard | Bedeutung |
| --- | --- | --- |
| `ADMIN_USERNAME` | `admin` | Admin-Benutzername |
| `ADMIN_PASSWORD` | kein Standard | Mindestens 12 Zeichen; ohne Passwort startet die App nicht |
| `DASHBOARD_TITLE` | `AppDashboard` | Name oben links und im Seitentitel |
| `APPDASHBOARD_IMAGE` | `ghcr.io/phillipunzen/appdashboard:latest` | Veröffentlichtes Image; alternativ Version oder Digest |
| `APPDASHBOARD_DATA_VOLUME` | `appdashboard_data` | Name des persistenten Docker-Volumes |
| `PORT` | `8080` | Auf dem Host veröffentlichter Port |
| `BIND_ADDRESS` | `127.0.0.1` | Bind-Adresse auf dem Host |
| `PUBLIC_ORIGIN` | leer | Öffentliche HTTPS-Adresse, z. B. `https://apps.example.de` |
| `SECURE_COOKIE` | `true` | Sitzungscookies nur über HTTPS senden |
| `TRUSTED_PROXY_HOPS` | `0` | Anzahl vertrauenswürdiger vorgeschalteter Proxys |
| `ALLOW_PRIVATE_METADATA` | `false` | Metadatenabruf im eigenen privaten Netz erlauben |
| `DATABASE_PATH` | `/data/dashboard.sqlite3` | Datenbankpfad im Container; bei eigenem Pfad den Volume-Mount anpassen |

Nach Änderungen in `.env`: `docker compose up -d`. Eine Passwortänderung meldet bestehende Admin-Sitzungen ab. Sitzungen laufen nach zwölf Stunden ab. Nach acht fehlgeschlagenen Anmeldeversuchen pro Quell-IP gilt eine Sperre von 15 Minuten; der Zähler übersteht Container-Neustarts.

Für eigene Docker-Konfigurationen unterstützt das Image alternativ `ADMIN_PASSWORD_FILE` (Datei im Container, z. B. `/run/secrets/admin_password`). Die mitgelieferte Compose-Datei verwendet `.env`; bei Umstellung auf Docker-Secrets entsprechend die Passwort-Umgebungsvariable und den Secret-Mount anpassen. Siehe [Docker-Dokumentation zu Secrets](https://docs.docker.com/compose/how-tos/use-secrets/).

## Sichern und wiederherstellen

App-Daten, Logos und der Sitzungsschlüssel liegen im Volume `appdashboard_data` (der Name ist unabhängig vom Checkout-Verzeichnis). Ein Container-Neustart oder Rebuild löscht diese Daten nicht. `docker compose down -v` entfernt ausdrücklich auch das Volume und damit alle Daten.

Im laufenden Betrieb eine konsistente SQLite-Sicherung erstellen:

```bash
mkdir -p backups
docker compose exec -T appdashboard python -m app.backup > backups/appdashboard.sqlite3
```

Das Skript nutzt die SQLite-Backup-API, sodass auch bei eingeschaltetem WAL-Modus eine konsistente einzelne Datei entsteht. Sicherungen enthalten alle öffentlichen App-Einträge und den Sitzungsschlüssel; vertraulich aufbewahren. `.env` separat sichern.

Wiederherstellen (ersetzt die vorhandene Sammlung; vorher sichern):

```bash
docker compose stop appdashboard
docker compose run --rm -T --no-deps appdashboard python -m app.backup --restore < backups/appdashboard.sqlite3
docker compose up -d
```

Alternativ steht in **Verwaltung → Sammlung als JSON exportieren** ein lesbarer Export mit Logos bereit. Ein JSON-Import ist nicht enthalten; zur vollständigen Wiederherstellung die Datenbanksicherung nutzen.

## Betrieb und Entwicklung

```bash
docker compose ps
docker compose logs --tail=100 appdashboard
docker compose pull
docker compose up -d
```

Der Container läuft als unprivilegierter Benutzer (UID/GID 10001), mit schreibgeschütztem Root-Dateisystem und Healthcheck unter `/healthz`. Gunicorn bedient die Anwendung; der Flask-Entwicklungsserver wird im Container nicht verwendet. Hintergrund: [Flask-Produktionsempfehlungen](https://flask.palletsprojects.com/en/stable/deploying/).

Lokal ohne Docker (Python 3.13):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export ADMIN_PASSWORD='ein-eigenes-langes-zufaelliges-passwort'
export DATABASE_PATH="$PWD/data/dashboard.sqlite3"
export SECURE_COOKIE=false
.venv/bin/gunicorn --bind 127.0.0.1:8130 'app:create_app()'
```

Tests:

```bash
.venv/bin/python -m unittest discover -s tests -v
node --check app/static/app.js
```

Die Tests prüfen unter anderem öffentliche Lesezugriffe, geschützte Verwaltung, CSRF, Passwortwechsel, Anmeldesperren, CRUD, Persistenz, Logos, Metadaten und den Schutz vor Zugriffen auf interne Adressen. Frontend: HTML/CSS/JavaScript ohne Build-Schritt. Backend: Flask, SQLite und Pillow.

Optionale Browserprüfung mit Playwright (Node.js wird nur für diese Tests benötigt):

```bash
npm ci
npx playwright install chromium
```

Die vollständige Prüfung startet selbst eine temporäre Testinstanz mit eigener Datenbank und zufälligem Passwort und beendet sie anschließend:

```bash
.venv/bin/python tests/run_browser.py
```

Screenshots für Desktop, Smartphone, Detailansicht und dunkles Design landen in `artifacts/`. Die darunterliegende Prüfung `npm run test:browser` darf ausschließlich gegen eine leere Wegwerf-Instanz ausgeführt werden; `tests/run_browser.py` richtet diese automatisch ein.
