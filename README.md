# Analisi Spettrale CC

Applicazione desktop in Python (PyQt5) per l’analisi di spettri da file CSV, con preprocessing, decomposizione dei picchi e esportazione dei risultati.

## Funzionalità principali

- Caricamento di uno o più spettri da CSV (prima colonna = asse X, colonne successive = spettri).
- Preprocessing con selezione intervallo di validità (`X1`, `X2`).
- Filtraggio/denoising con:
  - FFT Low-pass
  - Savitzky-Golay
- Decomposizione picchi con modelli:
  - Asymmetric Gaussian
  - Gaussian
  - Lorentzian
- Visualizzazione finale di:
  - segnale grezzo
  - segnale filtrato
  - somma dei picchi fittati
  - componenti dei singoli picchi
- Esportazione risultati in CSV (uno per spettro + file riassuntivo dei picchi).

## Requisiti

- Python 3.7 o superiore
- Windows 10+ (installazione guidata pronta)
- Pacchetti Python (installati automaticamente):
  - numpy
  - pandas
  - scipy
  - matplotlib
  - PyQt5

## Installazione rapida (Windows consigliato)

1. Apri PowerShell nella cartella del progetto.
2. Esegui:

```powershell
.\install.ps1
```

Se PowerShell blocca gli script, esegui una volta:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Poi rilancia `./install.ps1`.

### Cosa fa l’installer

- rileva Python (`py -3` o `python`)
- crea l’ambiente virtuale `.venv`
- installa le dipendenze
- crea `Analizzatore.bat`
- crea la cartella `results` (se non esiste)

## Avvio del programma

### Metodo consigliato (senza terminale)

```bat
Analizzatore.bat
```

Il launcher usa `.venv\Scripts\pythonw.exe` e avvia `main.py` senza finestra terminale.

### Metodo manuale

```powershell
& ".\.venv\Scripts\python.exe" .\main.py
```

## Formato file input CSV

Il file CSV deve avere almeno 2 colonne:

1. **Prima colonna**: valori X (es. Raman shift, frequenza, ecc.)
2. **Colonne successive**: intensità degli spettri

Note utili:

- Separatori supportati: `;`, `,`, tab
- Le righe non numeriche vengono scartate
- Se non ci sono righe numeriche valide, il caricamento fallisce

## Flusso operativo consigliato

1. **Preprocessing**
   - Seleziona il file
   - Imposta `X1` e `X2`
   - Scegli filtro e parametri
   - Esegui anteprima e conferma

2. **Decomposition**
   - Scegli spettro e modello di picco
   - Regola parametri (prominence, distance, hidden peak mode, ecc.)
   - Lancia la decomposizione

3. **Final Results**
   - Controlla grafico finale
   - Abilita/disabilita curve visualizzate
   - Esporta tutti i risultati in CSV

## Output esportati

Quando premi **Export all results to CSV**:

- viene creato un file `<nome_spettro>_results.csv` per ogni spettro
- viene creato `peaks_summary.csv` con il riepilogo globale dei picchi

La cartella di destinazione viene scelta dall’utente durante l’export.

## Struttura progetto (essenziale)

```text
Analisi_Spettrale_CC/
├── main.py
├── install.ps1
├── Analizzatore.bat
├── requirements.txt
├── sourcecode/
│   ├── gui_app.py
│   └── spectra_math.py
└── results/
```

## Risoluzione problemi rapida

- **Python non trovato**: installa Python da https://www.python.org/downloads/windows/ e abilita “Add python.exe to PATH”.
- **Errore su dipendenze**: riesegui `install.ps1` oppure:

```powershell
& ".\.venv\Scripts\python.exe" -m pip install --upgrade -r requirements.txt
```

- **La GUI non si apre**: verifica che `.venv\Scripts\pythonw.exe` esista e che `PyQt5` sia installato nell’ambiente virtuale.
