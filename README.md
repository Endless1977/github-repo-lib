# Repo Bibliotheek

Steam-achtige bibliotheek van open-source **spellen** en **apps** op GitHub.

- Filters voor spellen: soort spel, multiplayer/co-op, status (beta), grafische stijl, engine, leeftijd, laatst bijgewerkt, sterren
- Filters voor apps: categorie, platform, hosting (self-hosted), licentie, status
- Per repository: hoe je het start (online spelen, Releases, Docker of zelf bouwen) met directe links en commando's
- **Live scannen**: haalt actuele repositories op via de GitHub-zoek-API (werkt op GitHub Pages). Nieuwe resultaten worden in je browser bewaard; met een token klik je **Opslaan in repo** om ze in `data.json` vast te leggen.
- **Dagelijkse scan**: `.github/workflows/scan.yml` draait elke nacht `scripts/scan.py` en voegt nieuwe repos blijvend toe aan `data.json`. Handmatig starten kan via het tabblad *Actions* → *Bibliotheek scannen* → *Run workflow*.

## Bestanden

| Bestand | Wat |
|---|---|
| `data.json` | Alle repos in de bibliotheek (wordt nooit kleiner, alleen aangevuld) |
| `queries.json` | De zoekopdrachten voor spellen, apps en je eigen repos |
| `overrides.json` | Soort, beschrijving en labels voor repos zonder topics (zoals je eigen spellen) |
| `scripts/scan.py` | De scan; lokaal draaien kan met `python scripts/scan.py` |

Speel/bekijk: https://endless1977.github.io/github-repo-lib/
