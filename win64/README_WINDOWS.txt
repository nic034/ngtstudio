NGT Studio 2.5.21 - Windows (64-bit)                                      (Francais plus bas)
==========================================================================================

1. Unzip the WHOLE folder somewhere you can write to (Desktop, Documents, D:\NGT...).
   Do not run it from inside the zip, and avoid C:\Program Files.
2. Double-click NGT_Studio.exe. No Python needed: everything is included.

!!! THE JUKEBOX CARTRIDGE NEEDS YOUR OWN neogeo.zip (Neo Geo BIOS) - NOT INCLUDED !!!
    Use the neogeo.zip from your MAME setup. It is only needed for the "Cartridge" tab.
    Screen-saver objects: built in; your own jukebox_boxes.png ... jukebox_boxes6.png next to NGT_Studio.exe replace the built-in sheet of the same number.
    Extracting and listening only need your game romsets (not included either).
    Put it next to NGT_Studio.exe or in your MAME roms folder (folder of the last ROM opened):
    it is found automatically, otherwise NGT Studio asks for it.

- Windows may say "Windows protected your PC" (SmartScreen): the exe is not code-signed.
  Click "More info" then "Run anyway". Some antivirus programs flag PyInstaller executables
  by mistake; the full source code is published (MIT License) so anyone can check or rebuild it.
- At start-up NGT Studio asks for administrator rights (UAC). You can refuse: it works without.
  Command line without the prompt: NGT_Studio.exe --no-uac ...
- Files written next to the exe: the emulation engine (m1render_xxxxxxxx.exe), ngt_studio.log,
  ngt_output\ (default extraction folder), pictures\ (your own screenshots).
- Command line: NGT_Studio.exe --help (run it from cmd or PowerShell).
- Jukebox ROM: tested in MAME only, not yet on a real console, Darksoft or NeoSD.

==========================================================================================

1. Decompressez TOUT le dossier dans un endroit ou vous pouvez ecrire (Bureau, Documents, D:\NGT...).
   Ne le lancez pas depuis le zip, et evitez C:\Program Files.
2. Double-cliquez sur NGT_Studio.exe. Pas besoin de Python : tout est inclus.

!!! LA CARTOUCHE JUKEBOX A BESOIN DE VOTRE PROPRE neogeo.zip (BIOS Neo Geo) - NON FOURNI !!!
    Prenez le neogeo.zip de votre MAME. Il ne sert qu'a l'onglet "Cartridge".
    Objets de l'economiseur : integres ; vos jukebox_boxes.png ... jukebox_boxes6.png a cote de NGT_Studio.exe remplacent la planche integree de meme numero.
    Pour extraire et ecouter, il suffit des romsets des jeux (non fournis non plus).
    Mettez-le a cote de NGT_Studio.exe ou dans votre dossier roms de MAME (dossier de la derniere ROM
    ouverte) : il est trouve automatiquement, sinon NGT Studio le demande.

- Windows peut afficher "Windows a protege votre ordinateur" (SmartScreen) : l'exe n'est pas signe.
  Cliquez "Informations complementaires" puis "Executer quand meme". Certains antivirus signalent a tort
  les executables PyInstaller ; le code source complet est publie (licence MIT).
- Au demarrage, NGT Studio demande les droits administrateur (UAC). Vous pouvez refuser : il fonctionne sans.
- Fichiers ecrits a cote de l'exe : le moteur (m1render_xxxxxxxx.exe), ngt_studio.log, ngt_output\, pictures\.
- Ligne de commande : NGT_Studio.exe --help (depuis cmd ou PowerShell).
- ROM jukebox : testee sous MAME uniquement, pas encore sur console reelle, Darksoft ou NeoSD.

MIT License (c) 2026 Nicolas (Nic034). Third-party components: THIRD_PARTY_NOTICES.txt and licenses\.
