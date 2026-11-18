# AvangardeCam: notatki projektowe (PL)

Pełny dziennik decyzji, szczegółów i pułapek FreeCADa, po polsku. Przegląd po angielsku: [ARCHITECTURE.md](../ARCHITECTURE.md).
Ścieżki `src/Mod/AvangardeCam/` i `build/` pochodzą z czasów, gdy moduł był budowany razem z FreeCADem; dziś to dodatek w folderze `Mod`.

## Cel

FreeCAD liczy dobrze, ale jest nieczytelny. AvangardeCam to **nakładka i tłumacz**:
użytkownik pracuje w przejrzystym interfejsie, a program zamienia jego decyzje na
obiekty FreeCADa (Job, operacje CAM, narzędzia). Kod FreeCADa zostaje nietknięty.
Moduł to czysty Python, który działa po wrzuceniu do `Mod/` dowolnego FreeCADa 1.1.x.

Wcześniejsza łatka `src/Mod/CAM/Path/Tool/Controller.py` (posuwy i obroty z
narzędzi warsztatu) została wycofana: `src/Mod/CAM` to czysty FreeCAD 1.1.4,
a posuwy i obroty wpisuje tłumacz.

## Zasada „najlepsze z obu światów”

Trzy warstwy, zależności tylko w dół:

```
 ui/      okna, wstążka, lista projektu        (PySide, FreeCADGui)
   │
   ▼
 engine/  tłumacz: model → obiekty FreeCAD CAM  (jedyne miejsce, które zna API CAM)
   │
   ▼
 model/   opis projektu i operacji               (czysty Python: bez FreeCAD i bez Qt)
```

- **model/** opisuje *co* ma być zrobione: półfabrykat, narzędzie, operacja i jej parametry.
  Nie importuje FreeCADa, więc da się go testować zwykłym `python3` i nie psują go
  zmiany API FreeCADa.
- **engine/** opisuje *jak* to zrobić. Dziś `freecad_cam.py` tworzy i aktualizuje
  obiekty FreeCAD CAM, a `geometry.py` pracuje na geometrii detalu (płaskie ściany,
  normalne, punkt zerowy, szkice ze ścian). Jeśli kiedyś FreeCAD zacznie przeszkadzać, obok powstanie
  `native.py` (OCCT + libarea/Adaptive wyjęte z FreeCADa), a UI i model zostaną bez zmian.
  Gdy FreeCAD zmieni API (jak przy 0.21 → 1.0, Path → CAM), poprawiamy tylko tę warstwę.
- **ui/** pokazuje model i zbiera decyzje użytkownika. Nigdy nie woła API CAM
  bezpośrednio, zawsze przez engine.
- **post/** (obok engine, zależy tylko od model/): postprocesory. Engine buduje ze
  ścieżek FreeCADa neutralny program NC (`model/nc.py`), a postprocesor tylko go
  zapisuje pod konkretne sterowanie. Czysty Python, testowany `python3`.

**Funkcje w osobnych modułach** (zasada usera: „zmiana mierzenia nie może popsuć
wiercenia”). Nowa funkcja dostaje własny moduł silnika (`engine/<funkcja>.py`),
własny moduł UI (`ui/<funkcja>.py`) i własne testy (`tests/test_<funkcja>.py`,
`tests_gui/test_<funkcja>.py`). W `actions.py` i `handlers.py` ma tylko wpis i cienką
funkcję, która deleguje do swojego modułu. Wspólny kod (`geometry`, `freecad_cam`,
`picking`, `scene`) wolno wywoływać, ale nie przerabia się go pod nową funkcję. Gdy
funkcja potrzebuje czegoś innego, ma własną wersję u siebie. Zmianę wspólnego kodu
trzeba uzgodnić z userem i puścić wszystkie testy. Pierwszy tak zbudowany jest pomiar.

### Jednostki

Każda pomyłka jednostek to katastrofa, dlatego:
- model trzyma **tylko mm, mm/min i obr/min**, a jednostka jest w nazwie pola
  (`depth_mm`, `feed_mm_min`, `spindle_rpm`);
- przeliczenia robi wyłącznie engine, na granicy z FreeCADem;
- model waliduje zakresy (np. głębokość > 0, posuw > 0, krok boczny 1–100 %), zanim
  cokolwiek trafi do FreeCADa.

### Geometria

Odwołania do geometrii mają postać `GeometryRef(obiekt, ["Face12", "Edge3"])`.
Numeracja ścian i krawędzi pochodzi z OCCT, więc ta sama referencja zadziała też
w przyszłym natywnym silniku.

### Zapis w pliku

Specyfikacja operacji z modelu (JSON) zapisuje się w obiekcie dokumentu `.FCStd`
obok obiektu FreeCAD CAM, który z niej powstał. Po ponownym otwarciu pliku podwójny
klik otwiera **nasze** okno, a nie panel FreeCADa. Plik nadal otwiera się w czystym
FreeCADzie i tam zachowuje się jak zwykły Job.

## Mocowania i punkt zerowy

FreeCAD zawsze tnie wzdłuż osi Z, od początku układu Joba. Nie ma osobnego układu
współrzędnych dla operacji. Dlatego:

- **Projekt to lista mocowań (setupów), a mocowanie to jeden Job FreeCAD CAM.** Każde
  mocowanie ma swój punkt zerowy, półfabrykat, narzędzia (ToolControllery) i
  operacje. Pierwsze powstaje przy imporcie modelu, kolejne przez Snap-0-Point.
- **Punkt zerowy** to placement w układzie detalu (`freecad_cam.zero(job)`). W Jobie
  FreeCAD liczy na klonach modelu przesuniętych o odwrotność zera, więc X0 Y0 Z0
  Joba leży w zerze mocowania, a Z wskazuje stronę, z której przychodzi frez. Zero
  czytamy z klonów (`oryginał.Placement · klon.Placement⁻¹`), więc rozumiemy też
  Job ustawiony w samym FreeCADzie. Jego panel Joba robi to samo, tzn. obraca
  i przesuwa klon.
- **Snap-0-Point** (`geometry.zero_on_face`): Z to normalna ściany skierowana na
  zewnątrz, Z0 leży w płaszczyźnie ściany, a X0 Y0 w środku skrajnych wymiarów
  detalu wzdłuż nowych X i Y. Ściana górna i dolna zachowują X detalu (dolna
  obraca detal wokół X). Na ścianie bocznej Y idzie w górę, więc patrząc na ścianę
  X biegnie w prawo. Bez mocowania Snap tworzy pierwsze. Gdy aktywne mocowanie ma
  operacje, program pyta: przesunąć jego zero czy utworzyć nowe mocowanie.
  **Mocowania z konturami nie da się obrócić na inną oś**, bo linie ich szkiców
  muszą leżeć w poprzek narzędzia. Wtedy trzeba utworzyć nowe mocowanie. Odwrócenie osi
  (góra ↔ spód) jest dozwolone: szkice dalej leżą poziomo, tylko patrzą od frezu (najstarsze
  kontury, na klonie Draft szkicu, nadal blokują każdą zmianę osi).
- **Model złożony z obiektów** (np. STEP zaimportowany jako `App::Part` z bryłą
  `Part::Feature` w środku) podaje zaznaczenie inaczej. Klik w 3D daje kontener i
  ścieżkę (`Part__Feature.Face1`), a obserwatory zaznaczenia i `getSelectionEx()`
  dają wewnętrzną bryłę i `Face1`, której `owner()` nie zna. `freecad_cam.model_element`
  idzie od wewnętrznej bryły w górę do modelu (`model_path`) i odnajduje element w
  kształcie modelu: ten o tej samej topologii (`isPartner`), a przy kilku najbliższy.
  Nazwy topologiczne FreeCADa (człony ścieżki zaczynające się od `;`, które daje
  zaznaczenie bez rozwiązywania) usuwa `plain_sub`.
  Z tego korzystają Snap-0-Point, Extract boundary edges, wiercenie otworów
  klikniętych w modelu i `picking`. Wcześniej Snap na takim modelu mówił tylko
  „Select one flat face”.
- Domyślne zero (pierwsze mocowanie): środek detalu na jego górze.
- **Rotate 0-Point** (CAM > Setup: 90°, 180°, dowolny kąt w okienku, ostatni
  zapamiętany w `LastZeroRotation`; `freecad_cam.rotate_zero`, `frame.rotated_about_z`):
  obraca zero wokół jego osi Z przez X0 Y0, dodatni kąt przeciwnie do wskazówek zegara
  patrząc od strony freza (jak ROT sterowania; przy 90° nowe X = stare Y). Ćwiartki
  są dokładne, osie zostają czyste. Oś narzędzia się nie zmienia, więc kontury i
  wiercenia przeliczają się w nowym układzie. Kąt w Details (`zero_rotation`) liczymy
  od osi, jakie dałby Snap-0-Point (`axes_for_normal`), więc nie jest nigdzie
  zapisywany; Snap kasuje obrót. Półfabrykat to dalej pudełko FreeCADa w osiach
  mocowania: przy kącie innym niż wielokrotność 90° obejmuje obrócony detal, więc jest
  większy od surowego bloku.
  Przy obrocie o wielokrotność 90° naddatki obracają się z osiami
  (`BoxStock.turned_about_z`: przy 90° X− bierze stare Y−, Y− stare X+), więc blok zostaje
  tym samym blokiem — wcześniej naddatki zostawały przy osiach i blok 303 × 96 (X ±1,5,
  Y ±1,75) po obrocie robił się 303,5 × 95,5 (płyta testowa A). Przy innym kącie
  naddatki zostają przy osiach jak dotąd.
- **Move 0-Point** (CAM > Setup, duża ikona obok Snap-0-Point; `model/move_zero.py`,
  `engine/move_zero.py`, `ui/move_zero.py`, własne testy): zero zmienia miejsce (z opcją
  „5 axes” także kierunek osi, patrz niżej).
  Okno nie blokuje widoku 3D. Przesunięcie to X, Y, Z w mm wzdłuż osi mocowania, ze znakiem
  jak w przesunięciu punktu zerowego sterowania (X+476,5 = zero 476,5 mm dalej w X). **Select
  wall** + klik w płaską ścianę: zero idzie najkrótszą drogą na płaszczyznę ściany (rzut
  prostopadły, `to_plane`), więc ściana prostopadła do X zmienia tylko X, a pozostałe pola
  zostają; liczone od miejsca już wybranego w polach, więc druga i trzecia ściana dają
  narożnik, a ta sama ściana drugi raz nic nie zmienia. Ściana zaznaczona przed kliknięciem
  ikony jest brana od razu (jak przy Snap). Ściana nie zostaje zaznaczona. Walec = odmowa,
  przycisk czeka dalej. Zaznaczenie czytane 50 ms po kliknięciu (po `picking`, który klik w
  krawędź ze szkicem przenosi na linię szkicu).
  Podgląd: krzyż osi w miejscu docelowym i żółta linia od obecnego zera, rysowane w węźle
  Joba (czyli w układzie mocowania), bez testu głębi, nieklikalne; znikają przy OK/Cancel.
  OK = `engine.move_zero.move` w jednej transakcji „Move 0-Point”. Brak przesunięcia i
  obrotu = bez kroku undo. Limit 10 m na oś (literówki).
- **Select circle w oknie Move 0-Point** (2026-11-18, prośba usera na detalu testowym
  Soraluce: głowica obrócona o 90° wierci otwory w czole i czyści duży otwór; osobne moduły
  `model/engine/ui circle_zero.py`, `tests/test_circle_zero.py`,
  `tests_gui/test_circle_zero.py`). Klik w okrągłą krawędź (cały okrąg albo łuk) albo w
  ściankę walcową: zero do środka okręgu NA WYLOCIE otworu. Krawędź należąca do ścianki
  walcowej o tym samym promieniu i osi oznacza całą ściankę (współosiowe ścianki tego
  promienia, które się stykają — STEP dzieli walce na połówki). Wylot = koniec, za którym
  (wzdłuż osi, aż do końca pudełka detalu) narzędzie o promieniu r − min(0,1; r/10) nie
  trafia w detal (Boolean `common`); z dwóch wolnych końców ten, za którym mniej detalu
  w pasie 2·r wokół osi (otwór Ø600 wchodzący do komory: za końcem Y−720 są ściany komory
  aż do Y+1000); różnica ≤ średnica okręgu = remis → koniec kliknięty (krawędź), potem bliższy
  punktowi kliknięcia (`PickedPoints` przeliczone z układu widoku, sprawdzone: błąd 0 mm).
  Powód (zgłoszenie usera 2026-11-18): klik w głąb otworu łapał krawędź wewnętrznego końca
  (Edge37, Y−720), stara próba materiału dawała Z w stronę komory i zero na Y−720.
  Krawędź bez ścianki (stożek, płaski krąg): wolny kierunek osi; gdy oba albo żaden —
  próba materiału wokół okręgu (6 punktów, ±0,01 mm, `Shape.isInside`; mniej materiału =
  na zewnątrz). Brak wolnego końca (zamknięta pustka) → koniec kliknięty/bliższy + próba
  materiału. Czas na detalu Soraluce ≤ 0,12 s na klik. Wszystkie trzy pola Move są
  zastępowane. „5 axes” i „Z out of the model” ZAPAMIĘTYWANE (param `LastMoveZero5Axes`,
  `LastMoveZeroZOut`, prośba usera); zaznaczenie ich już po kliknięciu ściany/okręgu od razu
  daje obrót ostatniego kliknięcia (`_picked`, `_turn_out`). Bez 5 axes okno pisze, że oś
  nie idzie wzdłuż Z. Krawędź albo ścianka walcowa zaznaczona przed otwarciem okna = od razu
  okrąg; płaska ściana = jak dotąd ściana. Select wall i Select circle wzajemnie się
  wyłączają. Sprawdzone na Detal_testowy_Soraluce.step: każda krawędź i ścianka otworów
  Ø600 i Ø100 → wylot w czole Y−1000, Z = −Y (A+90) (druga strona Y+1000, A−90); otwory łap
  Ø70 (przelotowe) → koniec kliknięty; z zera na czole otwory Ø100 i Ø600 rozpoznawane do
  wiercenia.
- **Zera operacji (EKSPERYMENTALNE, gałąź `experimental`, nie puszczone na maszynie)**
  (`model/op_zero.py`, `engine/op_zero.py`, `ui/op_zero.py`, `tests/test_op_zero.py`,
  `tests_gui/test_op_zero.py`). Decyzja usera (2026-11-16): operacja liczy od zera, na którym
  powstała, i przy nim zostaje; zero jest „kursorem”. Mocowanie ma **zero domyślne** (preset
  maszyny, `AvangardeDefaultZero`) i **zero aktywne** (tam leżą klony modelu).
  - FreeCAD liczy Joba na jednym zerze, więc pracujemy na jednym naraz. Operacje z innego
    zera są **zaparkowane**: `AvangardeZero` (placement w układzie detalu) + `AvangardeParked`.
    FreeCAD 1.1.4 nie ma `freeze()` z Pythona, więc strażnik siedzi na
    `Path.Op.Base.ObjectOp.execute` (`op_zero.install`): zaparkowana operacja nie jest
    przeliczana i trzyma ścieżkę z własnego układu. Uwaga: FreeCAD zapamiętuje metody proxy
    w chwili przypisania, więc dla operacji sprzed instalacji strażnika trzeba `op.Proxy =
    op.Proxy` (`_guarded`). Właściwości są w pliku i w transakcjach, więc Undo i zapis działają.
  - `activate(job, place)`: parkuje żywe, ożywia operacje tego zera (`touch`, bo narzędzie
    albo stock mogły się zmienić), przestawia klony, dopasowuje stock, `_sync_operations`
    (pomija zaparkowane). Wołają to: Move 0-Point, Reset 0-Point, Make 0-Point active
    (menu operacji), Edit / Change tool na operacji z innego zera.
  - **Stock ma własny punkt zerowy** (user, 2026-11-16: „stock z własnym punktem zero; jak
    ktoś zrobi stock w innym miejscu, użyć zera domyślnego, liczonego z obecnego”):
    `AvangardeStockZero` = zero, na którego osiach blok jest pudełkiem (domyślne, na którym
    powstał), blok w jego układzie w `AvangardeBlock`, naddatki w `AvangardeDefaultStock`.
    Na innym zerze stock FreeCADa to pudełko opisane na bloku (ten sam blok przy obrotach
    co 90°, większe pudełko przy innych kątach; wtedy widok rysuje sam blok,
    `ui/op_zero.show_block`, a stock FreeCADa jest ukryty). Zmiana stocka idzie przez
    `cam.set_stock` → `op_zero.stock_changed`: wpisany na zerze o osiach wzdłuż domyślnego
    jest przeliczany na blok zera domyślnego (dokładnie). Pod innym kątem okna stocka (Stock,
    Details, Stock size) pracują wzdłuż własnych osi stocka i to piszą (`stock_edit`,
    `set_stock`). Set 0-Point as default pod innym kątem nie rusza bloku: stock zostaje przy
    swoim zerze, BLK FORM to pudełko opisane, a symulacja tnie sam blok (`_tilted_block`
    jako siatka startowa).
  - **5 osi w oknie Move 0-Point**: pole „5 axes” odsłania „Z out of the model” (Select wall
    obraca Z na zewnątrz ściany najkrótszym obrotem, `turn_onto`: ściana +X = 90° wokół Y,
    jak SPB90 w programach warsztatu) i pola „Turn about X / Y / Z”. Kąty to kąty
    przestrzenne sterowania: A, B, C wokół nieruchomych X, Y, Z w tej kolejności, czyli
    R = Rz(C)·Ry(B)·Rx(A) (`axes_of`, `turn_of`; przy B = ±90° A = 0). Jeden kąt naraz jest
    jednoznaczny; złożone kąty do sprawdzenia na maszynie.
  - **Snap-0-Point i Rotate 0-Point** ruszają całe mocowanie (zero domyślne z tym, co od
    niego liczy) i działają tylko z zera domyślnego (`before_setup_move`), inaczej komunikat.
    Mocowanie, którego zero nigdy nie odjechało, nie ma żadnej z tych właściwości i działa
    po staremu.
  - **Program NC**: `op_zero.setup_program` objeżdża zera (aktywne pierwsze), czyta operacje
    tam, gdzie są policzone, i wraca; z włączonym undo to porzucona transakcja (bez kroku
    undo, bez ponownego liczenia). `nc_program` daje `Operation.zero` (Frame względem
    presetu) i ruchy liczone od tego zera. BLK FORM zawsze z zera domyślnego.
  - **Symulacja 5 osi** (user, 2026-11-16; `model/tilted.py`, `model/crashes_tilted.py`,
    `stocklab/oblique.py`, `tests/test_tilted.py`, `tests_gui/test_zero_stock_play.py`):
    Play, Verify, czas cyklu i stock dla następnego mocowania puszczają każdą operację z jej
    zera. Ruchy maszyny liczone są w układzie operacji (kompensacja promienia, cykl wiercenia
    bez zmian), potem przenoszone do układu presetu, gdzie leży stock i detal; oś narzędzia
    = Z tego zera. `stocklab` tnie narzędziem wzdłuż X/Y/Z stocka starym kodem (ściany
    bloku), a pod dowolnym kątem nowym `oblique.py`: narzędzie jako stożki, przedział
    zbierany z promienia liczony dokładnie (kwadryka w (t, s) + cztery proste; ekstrema w
    kilkunastu punktach). Zgodność ze starym kodem dla osi prostych co do 1e-6, pochylone
    w granicach 0,5 % objętości. Kule i torusy jako najwyżej 12 cięciw na ćwiartkę
    (0,2 % promienia), w stocku tyle, żeby cięciwa zostawiała do 1/20 komórki
    (`CHORD_CELLS`); wysoki stożek cięty w kawałkach o wysokości średnicy (`PIECE_CELLS`).
    Szybkość (zmierzone 2026-11-16, 4 rdzenie, stock 250 komórek, frez Ø8, ruchy 1 mm):
    pod dowolnym kątem ok. 1,5–2 ms na ruch frezem płaskim i ok. 5 ms z promieniem naroża,
    wzdłuż osi stocka (ściany pod 90°) 0,1–0,3 ms. Czas idzie w `oblique.interval`
    (każdy promień pod narzędziem przy każdym ruchu, 14 punktów kandydatów); wątki nie
    pomogły (sprawdzone), do przyspieszenia zostaje tańszy wzór dla walca albo odsiew
    promieni, z których poprzedni ruch już wszystko zebrał.
    Kolizje (FMAX w materiale, chwyt) przy narzędziu nie z +Z: `crashes_tilted` pyta stock
    „ile by zabrał” (`oblique.would_take`) i tnie osobno tylko podejrzane ruchy. Verify
    („za głęboko”) dla osi pod kątem liczy w układzie narzędzia (`stocklab/verify.gouges`).
    Maszyna między zerami (`model/machine.py` + `tilted.arrive`): Bridgeport przed zmianą
    przesunięcia jedzie na Z100 presetu; maszyna z obracaną głowicą (`anew`) zaczyna każdą
    operację od Z100 nad jej zerem — drogi głowicy (M91) nie ma w programie, więc nie jest
    rysowana ani liczona w czasie. `post/machines.able`: program maszyny wybranej przy
    eksporcie, a gdy jest obrócone zero — pierwszej, która pochyla (lista w Play też jej).
    Siatka detalu i stock startowy idą do symulacji w układzie zera DOMYŚLNEGO
    (`op_zero.on_default`, `start_mesh`); Verify rysuje wynik przesunięty tam, gdzie widok
    ma detal na aktywnym zerze. Uwaga do testów: promień stojący dokładnie na krawędzi
    narzędzia bywa zbierany albo nie, zależnie od podziału ruchu (stary kod też) — w
    testach rozdzielczość bez takich promieni (97).
  - Widok: `scene.apply` rysuje zaparkowaną operację na jej własnym zerze
    (`op_zero.drawn_at`); w drzewie dopisek „(other 0-Point)”, w Details `ParkedView`.
- **Postprocesory osobno dla maszyn** (`post/machines.py`, wybór jako typ pliku w oknie
  eksportu, pamiętany w parametrze `Postprocessor`):
  - `post/heidenhain.py` — Bridgeport V1000 (sprawdzony). Nowe, eksperymentalne: przesunięte
    zero jako `CYCL DEF 7` (przed zmianą przesunięcia pod narzędziem najpierw Z100 na
    presecie, reset przed końcem narzędzia i programu); obrócone zero = odmowa z nazwą operacji.
  - `post/soraluce.py` — Soraluce T35, obracana głowica (eksperymentalny, wzór: program
    warsztatu). Każda operacja osobno: `CALL LBL "RESET"`/`"FREE"`, TOOL CALL, głowica w górę
    (M91), `CYCL DEF 7`, `M138 A B`, `PLANE SPATIAL … STAY COORD ROT`, `CYCL DEF 397`, `L Z100`,
    ruchy z M13 na pierwszym, `M9`; na końcu etykiety RESET, FREE, HEAD0. Wiercenie na razie
    cyklem 205 z `CYCL CALL POS` (jak Bridgeport), nie 200/203 z M99.
  Do zrobienia: sprawdzenie na maszynie; czasy i dynamika Soraluce (teraz Bridgeporta, bez
  drogi głowicy); wiercenie Soraluce 200/203 z M99; kopia `stocklab/oblique.py` do repo Lab.
- Półfabrykat „z modelu” FreeCAD ustawia tylko przy tworzeniu, więc po każdej
  zmianie zera tłumacz przestawia go sam (`_place_stock`).
- **Stock size...** (przycisk w Details stocka; `model/stock_size.py`, `engine/stock_size.py`,
  `ui/stock_size.py`): user wpisuje X, Y, Z bloku, model ląduje na jego środku — po
  połowie nadwyżki z każdej strony w X, Y i Z. Zapisywane jako zwykłe naddatki `BoxStock`
  (jeden krok undo), więc pola naddatków pokazują wynik, a zmiana modelu lub obrót zera
  zmienia blok jak dotąd (rozmiar nie jest pamiętany). Wymiar mniejszy od modelu
  (tolerancja 1e-6 mm) = komunikat, okno zostaje otwarte. Obrys modelu: ten sam
  `shapeBoundBox` klonów co `_place_stock`, czyli w osiach mocowania.
- **Okno Stock** (CAM > Stock na wstążce, `handlers.stock_window`, `ui/stock_dialog.py`): to
  co Details stocka, w oknie jak Contour tooling, z obrazkiem obok pól (`stock_allowances.svg`,
  przy Size X/Y/Z `stock_size.svg`; obrazki rysowane rzutem orto z Blendera,
  nie z Blendera). Size X/Y/Z kładzie model na środku tej osi, naddatek zmienia rozmiar osi;
  stock zmienia się dopiero na OK (jeden krok undo). Stock FreeCADa o stałym wymiarze: pola
  startują od jego zasięgu poza modelem, OK zamienia go na pudełko z naddatkami.
- Planowane: dowolne przestawianie zera (wartości wpisywane ręcznie) i liczenie
  operacji od niego.

### Next setup: stock nowego mocowania (2026-10-30)

Prośba usera: przycisk „Next setup” na zakładce CAM (grupa Setup) i okno z wyborem, od czego
zaczyna nowe mocowanie (`ui/next_setup.py`, `engine/next_setup.py`, `model/start_stock.py`,
testy `tests/test_start_stock.py` i `tests_gui/test_next_setup.py`):

- **Stock from Setup N** (domyślnie, decyzja usera): to, co zostawia program mocowania N
  (domyślnie ostatniego), cięte jak w Verify (bez sprawdzania detalu) z dokładnością
  Rough/Medium/Fine (pamiętana w `LastNextSetupAccuracy`), w wątku w tle z okienkiem
  „busy”. Siatka powierzchni (`stocklab.surface`) idzie do układu detalu (zero mocowania N)
  i zostaje w dokumencie jako ukryty `Mesh::Feature` (rola `stock-source`). Liczona raz;
  po zmianie mocowania N przycisk **Work it out again** w Details stocka (ta sama
  dokładność, jeden krok undo). Program mocowania N nie jest pilnowany: stock się nie
  przelicza sam (moja decyzja: przeliczenie trwa sekundy).
- **Standard stock**: pudełko z naddatkami, jak każde nowe mocowanie.
- **Custom stock**: model półfabrykatu z pliku (odlew od odlewni), STEP/IGES/BREP jako bryła
  (`Part::Feature`), STL/OBJ/PLY jako siatka (musi być zamknięta). Leży tam, gdzie go
  narysowano, czyli w układzie detalu — albo (od 2026-11-17, niżej) środkiem na środku modelu.
- Stock Joba to wtedy `Part::FeaturePython` (Job FreeCADa wymaga proxy widoku stocka,
  `IconViewProvider` „Stock”) z własnościami `AvangardeStockKind/Source/From/Accuracy/Made/File`,
  w układzie mocowania: bryła odlewu albo **pudełko** siatki (operacje FreeCADa czytają tylko
  obrys stocka; Adaptive i Simulate biorą siatkę same, niżej). `next_setup.place` przestawia go po każdej zmianie zera
  (jedna linijka w `freecad_cam._place_stock`); `forget` usuwa źródło, gdy stock zamienia się
  na pudełko (`set_stock`).
- Widok: przy aktywnym mocowaniu rysowana jest siatka stocka zamiast jego pudełka
  (`ui.next_setup.show_stock` z `scene.apply`; siatka jest w układzie detalu, jak cały widok).
  Lista: „Stock  From Setup 1 …”, „Stock  Blank …”, „Stock  Box …”.
- Verify i Play zaczynają od materiału ze stocka (`next_setup.start_mesh` → siatka w układzie
  mocowania → `stocklab.Stock.from_mesh`, Lab a03f938): ruch szybki w miejsce wyfrezowane w
  mocowaniu 1 nie jest kolizją, a gwint w otworze wywierconym w mocowaniu 1 nie jest już
  fałszywym alarmem (mały stock otworu też z siatki). Utrata ok. pół komórki na ścianach przy
  każdym przeniesieniu (objętość ~99,8 %).
- **Adaptive na stocku z siatki** (prośba usera 2026-10-30: „adaptive i symulacja w drugim
  mocowaniu powinny czytać z prawdziwego stocka”): `next_setup.material` robi z siatki model
  stocka (`stocklab.Stock.from_mesh`, dokładność, z jaką go policzono, albo 250 dla STL), a
  `engine/adaptive._stocks` daje libarea na każdym poziomie to, co z niego jest **od poziomu
  do poziomu nad nim** w tym samym obszarze (`start_stock.area` → `stocklab.area(..., apart=True)`,
  Lab 50988c1: ostrożnie, nigdy mniej niż materiał; libarea bierze stock jako jeden obrys z
  dziurami, więc kilka kawałków materiału to ich otoczka wypukła z dziurami bez kawałków w
  środku). Nad tamtym poziomem narzędzie już zebrało materiał w tym obszarze, więc pod
  schodami zostawionymi przez mocowanie 1 nie ma ścieżek w powietrzu. Pierwszy poziom obszaru
  widzi wszystko do góry stocka. Poziom pomijany (`_nothing_left`), gdy cały materiał leży
  w pasie Finish XY + 2 przekątne komórki przy krawędziach obszaru albo jest go mniej niż
  komórka: obrys ostrożny jest do przekątnej komórki większy od materiału, a siatka po
  mocowaniu 1 ma dna zaokrąglone przy ścianach (narożniki siatki, do pół komórki; w teście
  75 µm 0,13 mm od ściany), więc libarea objeżdżałaby ścianę w powietrzu na każdym poziomie.
  Materiał pominiętego poziomu zostaje, więc kolejne poziomy obszaru widzą go aż do miejsca,
  gdzie się zaczynał, i kawałek zaczyna się stamtąd (szybki zjazd tylko nad nim, żadnych
  przelotów na szybkim przez resztki). Dno wycięte w mocowaniu 1 leży w siatce kilka µm niżej
  (1,4 µm w teście): warstwa kończy się `FLOOR_MM` = 0,01 mm pod poziomem nad nią. Klasyfikacja
  obszarów zostaje FreeCADa (na pudełku), dla zaznaczonych den (`_regions`) materiał nad
  poziomem. Bryła odlewu ze STEP-a jest stockiem Joba, więc Adaptive czyta ją jak dotąd
  (`solid_projection`). `FreeCAD makeOffset2D` na ścianie otworu działa odwrotnie (powiększa
  przy ujemnym), stąd `_offset` sprawdza pole. Test: płyta z otworem, mocowanie 1 zbiera pierścień
  i otwór do 8 mm, mocowanie 2 od spodu do Z-10 tnie tylko Z-2 i Z-4 (346 ruchów zamiast 2199,
  0,65 s). Płyta testowa A (kopia): Adaptive z siatką 10 s, z tego warstwy 0,84 s i model
  0,26 s; ścieżka ta sama co z pudełkiem (mocowanie 1 nie ruszało pierścienia wokół płyty).
- **Simulate** (symulator OpenGL FreeCADa) startuje z siatki (`next_setup.simulator_stock`,
  jedna linijka w `ui/simulation.start`): symulator numeruje wierzchołki 16 bitami (najwyżej
  21845 trójkątów, każdy trójkąt to ściana z 3 wierzchołkami), więc siatka jest upraszczana
  (`Mesh.decimate`) do `SIMULATOR_TRIANGLES` = 8000 i zamieniana na ściany (`makeShapeFromMesh`,
  ~1 s; objętość bez zmian). Placement kopii siatki = zero⁻¹ · Placement źródła.
- Zero nowego mocowania: zaznaczona płaska ściana (jak Snap-0-Point), bez niej zero
  ostatniego mocowania — potem Snap-0-Point na ścianie nowego zamocowania (bez operacji
  tylko przesuwa zero, stock idzie za nim).
- Mocowanie i jego stock to **jeden krok undo** „Next setup”. Do tego `new_setup` nie woła
  już `PathJobGui.Create` (otwiera i zamyka własną transakcję „Create Job”), tylko robi to
  samo bez transakcji, a na czas tworzenia Joba FreeCAD nie robi domyślnego freza 5 mm
  (`_no_default_tool`): wczytanie jego bryły (PartDesign z pliku) zamykało otwartą
  transakcję w GUI, przez co nowe mocowanie (też z Snap-0-Point „New setup”) było kilkoma
  krokami undo, a ostatni cofał się do połowy. Frez i tak był od razu usuwany.

### Custom stock: własny stock z pliku w każdym mocowaniu (2026-11-17)

Prośba usera: „trzeba dodać możliwość importowania custom stocka, najłatwiej znajdywać środek
stocka i wrzucać go na środek modelu”. Przycisk **Custom stock** na wstążce (grupa Setup, obok
Stock), przycisk **Custom stock...** w oknie Stock (zamyka je i otwiera okno Custom stock) i w
Details stocka; okno: plik + „Put the middle of the stock in the middle of the model”
(domyślnie zaznaczone, pamiętane w `LastBlankInMiddle`, wspólne z Next setup).

- Ten sam rodzaj stocka co Custom w Next setup (`next_setup.set_custom_stock`, CUSTOM, źródło w
  układzie detalu), więc Play/Verify/Adaptive/Simulate działają jak dotąd. Nowe moduły:
  `model/custom_stock.py` (środek obrysu, przesunięcie, gdzie model wystaje — czysty Python),
  `engine/custom_stock.py` (`load`, `centre`, `off_middle`, `sticking_out`),
  `ui/custom_stock.py` (okno, jeden krok undo, komunikaty), testy `tests/test_custom_stock.py`
  i `tests_gui/test_custom_stock.py`.
- Środki liczone na osiach **mocowania** (to, co user widzi i mierzy): obrys modeli taki, wokół
  którego powstaje zwykły stock (`stock_size.models_bounds`), i obrys surówki
  (`optimalBoundingBox`, ciaśniejszy niż `BoundBox` przy ścianach krzywych). Przesunięcie
  obracane do układu detalu (`zero.Rotation`) i dopisywane do `Placement` źródła, więc stock
  idzie za zerem jak dotąd (test z mocowaniem od spodu, sprawdzony mutacją).
- Obrysy z **dokładnych ścian** (`optimalBoundingBox(False, False)`, także modelu:
  `custom_stock.models_bounds`), nie `BoundBox`: w GUI, gdy kształt jest już narysowany, OCC
  bierze `BoundBox` z trójkątów widoku, a te leżą wewnątrz dużych łuków. Plik testowy usera
  (Detal_testowy_Soraluce, 1030 × 2400 × 1260): góra obrysu 513,56 zamiast 515 (−1,44 mm),
  przez co środek wychodził o 0,72 mm za nisko. Bez GUI tego nie widać (FreeCADCmd nie
  rysuje), test silnika sprawdza tylko dokładny obrys łuku. Ten sam błąd ma zwykły stock z
  naddatkami (`PathStock.shapeBoundBox`): na tym detalu jego góra wychodzi 0,44 mm POD górą
  detalu — naprawione 2026-11-18 na prośbę usera („popraw też zwykły stock”):
  `engine/exact_box.py` podmienia `Path.Main.Stock.shapeBoundBox` (wołane przez nazwę w
  module, więc bierze je `StockFromBase.execute`, Job FreeCADa, `stock_size.models_bounds`,
  `_place_stock`) na obrys z dokładnych ścian; instalowane przy imporcie `freecad_cam` (jak
  strażnik operacji w `op_zero`). Pliki otwarte ze starym stockiem przeliczą się przy
  najbliższym recompute (stock robi się poprawny). Na detalu usera: góra stocka 1 mm nad górą
  detalu (było −0,44). Test GUI `test_exact_stock.py`; mojego kształtu (płyty z łukiem R 515
  jak u usera, 2400 długości) FreeCAD akurat NIE zaniża — wierzchołek siatki trafia w szczyt
  łuku, więc „za niski obrys” tylko w logu; na pliku usera (`AC_EXACT_STEP`) zaniża i test
  przechodzi.
- **Surówka narysowana wokół detalu zostaje** (decyzja usera 2026-11-18, „okej”): gdy obrys
  modelu mieści się w obrysie surówki z pliku (do `FITS_MM` = 0,1 mm, trójkąty STL na łukach),
  `load` jej nie przesuwa nawet z kratką; środek tylko dla surówki narysowanej gdzie indziej.
  Odlew usera ma 8 mm naddatku tylko od spodu — środek dzieliłby go 4/4.
- **Move stock...** (prośba usera: przesuwanie po osiach po prawym kliku na stock): menu Stock
  w liście projektu (`custom_stock.stock_menu`: Move stock..., Put in the middle dla CUSTOM;
  Custom stock..., Stock... zawsze), okno X/Y/Z na osiach mocowania (`engine.custom_stock.move`,
  jeden krok undo, komunikat gdy model wystaje). Prawy klik w 3D nie — stock w 3D nie jest
  klikalny (Selectable = False, żeby klikać ściany modelu przez niego).
- **Tylko przesunięcie, bez obrotu** (moja decyzja: „najłatwiej”). Gdy obrys modelu wystaje
  poza obrys surówki (> 0,01 mm), surówka i tak jest wczytywana, a komunikat mówi o ile i z
  której strony (np. odlew obrócony o 90°). Sprawdzane są tylko obrysy: odlew z kieszenią tam,
  gdzie detal jest pełny, nie jest wykrywany.
- Details: wiersz **Middle** („on the model's middle” albo „X … Y … Z … mm off the model's”,
  odświeżany w `update_view`) i przycisk **Put in the middle** (jeden krok undo).
- Widok: surówka z pliku siatki (STL…) rysowana jest sama, przezroczysta, zamiast pudełka
  wokół niej (`ui.next_setup.show_stock`, jak stock z mocowania); wcześniej było widać tylko
  pudełko (zgłoszenie usera 2026-11-17). Surówka ze STEP-a to sam stock Joba, rysowana jak jest.
- Next setup: Custom ma tę samą kratkę; `choice()` daje `(CUSTOM, ścieżka, środek)`, stara
  postać `(CUSTOM, ścieżka)` działa jak dotąd (bez przesuwania).

### Widok 3D (`ui/scene.py`)

Widok pokazuje detal tak, jak leży w **aktywnym mocowaniu**, czyli jak na
maszynie. Na szczycie sceny każdego widoku 3D (przed węzłem `EditingRoot`, więc
światła się nie obracają) stoi `SoTransform` „AvangardeCamSetupFrame” równy
odwrotności zera aktywnego mocowania (`scene.view_placement`). Zero leży w
początku układu, a oś narzędzia jest w górze. Dzięki temu sześcian nawigacyjny
FreeCADa (NaviCube), który zawsze pokazuje osie świata wzięte z kamery, oraz
widoki Top i Front są widokami mocowania. NaviCube nie ma własnego układu
odniesienia, a druga droga (obracać tylko sześcian) wymagałaby łaty w C++.
Po zmianie mocowania albo jego zera widok obraca detal i od razu, w tym samym
przerysowaniu, dopasowuje kadr (`scene._fit`: `fitAll` przy wyłączonej animacji
kamery). Animowany `fitAll` FreeCADa najpierw pokazywał detal przeskoczony w nowe
miejsce, a potem oddalał i przybliżał kamerę. Import STEP robi wszystko naraz
(`scene.show_all`): najpierw układ mocowania, potem widok izometryczny i kadr.
Wcześniej kamera ruszała się dwa razy, przed obróceniem sceny i po nim. Punkty FreeCADa z kliknięć (`pnt` obserwatorów) są już w układzie
widoku. Punkt dokumentu przelicza na ekran `scene.to_view`: używają go strzałki
kierunku i kliknięcia w testach.

Pokazujemy oryginały modeli, a klony Jobów są ukryte. Obiekty Joba (półfabrykat, ścieżki i trójnóg osi, który FreeCAD sam
rysuje w początku Joba) rysujemy przesunięte o zero mocowania. Robi to `SoTransform`
wstawiony na początek węzła sceny ich ViewProviderów. To zmienia tylko rysowanie,
a dokument zostaje bez zmian (poza widocznością). Dzięki temu ścieżki leżą na
detalu, a trójnóg FreeCADa stoi na zerze. Widać tylko **aktywne mocowanie**, czyli
to, którego pozycję zaznaczono na liście. Dwuklik na obiekcie projektu w 3D
otworzyłby edytor FreeCADa w ukrytym panelu, więc obserwator `slotInEdit` go
zamyka i pokazuje obiekt w naszym panelu. W trybie eksperta widok wraca do
FreeCADa (klony aktywnego mocowania, bez przesunięć i bez układu mocowania).

**Ścieżka zaznaczonej operacji jest czerwona** (`scene.highlight_operation`), żeby
było widać, która operacja co robi. Jej ruchy robocze (G1/G2/G3, łącznie z
wejściem w materiał) rysujemy jeszcze raz, czerwono i grubo (3 px), jako
`SoSeparator` dopięty na koniec węzła sceny operacji. Dzięki temu przesuwa się
razem z zerem mocowania. Ta nakładka ma wyłączony test głębokości, bo kontur
zwykle leży pod ścianą, wzdłuż której idzie, i bez tego byłby zasłonięty. Własnych
kolorów FreeCADa (NormalColor, LineWidth) nie zmieniamy, więc dokument zostaje
nietknięty. Przejazdy szybkie zostają cienkie i ciemnoczerwone, tak jak rysuje je
FreeCAD. Nakładkę budujemy od nowa przy każdym odświeżeniu panelu, czyli także po
przeliczeniu ścieżki.

**Kontur z kompensacją RL/RR rysujemy sami** (`freecad_cam.path_drawing`,
`scene._draw_path`; decyzja usera). Ścieżka FreeCADa to środek freza (z niej
liczą się symulacja i program), ale programista chce widzieć, gdzie tnie krawędź.
Rysunek: przejazdy szybkie i zejście w materiał tam, gdzie idzie środek; wzdłuż
konturu linie programu (`Run.program`, czyli krawędź freza, każde przejście XY
osobno); gdzie środek i krawędź się rozchodzą (bez dojazdu po łuku: zejście obok
linii), łączy je żółta linia (`PATH_LINK_COLOR`), tam i z powrotem. Z dojazdem po
łuku program zaczyna się i kończy w środku łuku, więc żółtych linii nie ma. Linie
FreeCADa (jego `SoBrepEdgeSet`) wkładamy w jego miejscu w `SoSwitch`
(`_FREECAD_LINES_NAME`) i wyłączamy; FreeCAD dalej je aktualizuje, a w trybie
eksperta albo bez kompensacji wracają. Nasz rysunek jest niewybieralny, więc
klik w taką ścieżkę w 3D nie zaznacza operacji. Czerwone podświetlenie idzie wtedy
po krawędzi. Rysunek liczymy ponownie tylko przy zmianie ścieżki (`scene._drawings`,
klucz to G-code ścieżki).

**Menu operacji** (`project_panel.operation_menu`). Klik prawym przyciskiem na
operację na liście zaznacza ją i otwiera menu w miejscu kliknięcia (menu
kontekstowe drzewa, `customContextMenuRequested`). Lewy klik tylko zaznacza. Menu
ma między innymi:

- **Edit...** (`handlers.edit_operation`) otwiera okno, w którym operacja powstała
  (Contour tooling albo Drilling), z jej wartościami i narzędziem. Tytuł okna to
  „Edit <nazwa>”. OK zmienia wartości i narzędzie naraz (`freecad_cam.change_operation`,
  jeden krok cofania), a wartości sprawdzane są już z nowym narzędziem. Linie i
  otwory zostają bez zmian. Okno edycji nie pokazuje ani nie zapamiętuje „ostatnio
  użytych” wartości nowych operacji. Promień dojazdu, który szedł za narzędziem
  (None), dalej za nim idzie.
- **Switch off / Switch on** (`freecad_cam.set_active`) przełącza `Active` FreeCADa
  i jest krokiem cofania. Wyłączona operacja nie ma ścieżki i nie trafia do
  programu ani do symulacji. Na liście ma dopisek „(off)” i jest szara.
- **Hide in 3D / Show in 3D** (`scene.set_hidden`) ukrywa tylko widok. Stan żyje w
  sesji i nie jest zapisywany w pliku, tak samo jak aktywne mocowanie. Ukryta
  operacja dalej jest w programie, a na liście ma dopisek „(hidden)”.
- **Delete** (`ui/delete_operation.py`), ostatnie, za kreską; to samo robi klawisz
  Delete na zaznaczonej operacji listy.

**Usuwanie operacji** (`ui/delete_operation.py`). Operacja znika razem z obiektami
pomocniczymi, które AvangardeCam dla niej zrobił (linie/okręgi szkicu,
`freecad_cam.remove_operation`), w jednym kroku cofania „Delete operation”; Undo
przywraca ją na jej miejsce w kolejności. Działa też na operacjach zrobionych w
FreeCADzie. Narzędzia mocowania zostają. Potem zaznaczona jest następna operacja
mocowania, a gdy to była ostatnia, poprzednia; po jedynej grupa Operations. Pasek
stanu mówi „<nazwa> deleted. Undo brings it back.” Ukrycie w 3D jest zdejmowane
przed usunięciem (stan po nazwie, a nowa operacja może dostać tę samą nazwę).
Klawisz Delete: filtr zdarzeń drzewa przyjmuje `ShortcutOverride`, gdy bieżący
wpis to operacja, więc klawisz trafia do listy, a nie do FreeCADowego Std_Delete;
na innych wpisach Delete działa jak wcześniej. Przycisk Remove operation w
szczegółach operacji zostaje bez zmian.

**Ukrywanie szkicu** (`ui/sketch_visibility.py`). Klik prawym przyciskiem na
szkic na liście zaznacza go i otwiera menu z jednym poleceniem: Hide in 3D /
Show in 3D, jak przy operacji. To zwykła widoczność FreeCADa (`Visibility`
szkicu), więc w odróżnieniu od operacji zapisuje się w pliku. Ukryty szkic ma na
liście dopisek „(hidden)” i jest szary; jego linii nie widać i nie da się ich
kliknąć, strzałki kierunku znikają (`direction` patrzy na `Visibility`). Kontury
zrobione na szkicu zostają widoczne i w programie. `scene.apply` szkiców nie
pokazuje na siłę, więc ukrycie trwa.

**Kolejność operacji** (`ui/operation_order.py`, `engine/operation_order.py`,
`handlers.move_operation`). Operacje mocowania idą w kolejności grupy
`Operations` Joba; program, symulacja, Verify i czas cyklu czytają ją stamtąd.
Przeciągnięcie operacji na liście (lewy przycisk wciśnięty na operacji i ruch
myszy dalej niż `startDragDistance`) rysuje linię tam, gdzie trafi; puszczenie
przestawia ją w grupie w jednym kroku cofania i zostawia ją zaznaczoną. Tylko
w obrębie własnego mocowania (operacja używa narzędzi swojego mocowania): poza
operacjami mocowania kursor „zakaz” i brak linii, tak samo w miejscu, gdzie już
jest. Esc przerywa. Filtr zdarzeń na viewporcie drzewa połyka ruchy myszy z
wciśniętym przyciskiem na operacji (inaczej drzewo przesuwałoby zaznaczenie),
a zmienia dokument dopiero `QTimer.singleShot(0)` po puszczeniu, bo lista
budowana jest wtedy od nowa. Wpis przeciąganej operacji szukany jest za każdym
razem po nazwie (lista mogła się przebudować w trakcie). Wbudowanego
drag & drop Qt nie używamy: przestawiałby wpisy listy zamiast dokumentu.

## Szkice i Contour tooling

- **Extract boundary edges** (`geometry.extract_boundary`): szkic z krawędzi
  zaznaczonej płaskiej ściany (obrys i otwory). To kopia, a nie odwołanie do
  ściany, więc przetrwa zmianę modelu. Szkic leży w płaszczyźnie ściany z tymi
  samymi osiami i początkiem, jakie dałby Snap-0-Point na tej ścianie, czyli
  **współrzędne szkicu = współrzędne G-code** mocowania zaczepionego na tej ścianie.
  Ale **szkic nie ma własnego punktu zerowego** (decyzja usera 2026-10-29): program bierze
  jego linie tam, gdzie leżą na detalu, liczone od zera mocowania (X, Y i Z płaszczyzny).
  Details szkicu pokazują **Lines at** = Z płaszczyzny od zera każdego pasującego mocowania.
  Łuki są zawsze krótszym łukiem, który pokrywa krawędź, a krzywe B-spline są
  przycinane do krawędzi.
- **Wygląd szkicu** (`scene.style_sketch`, `profile.apply_colors`): linie szkicu
  są zielone i grube (4 px, a krawędzie modelu 2 px, czarne). To, co zaznaczone,
  jest czerwone (kolor zaznaczenia FreeCADa, ustawiany przy każdym starcie).
  Najechanie myszą jest żółte, a nie zielone, żeby nie udawało szkicu. Szkic jest
  rysowany o włos bliżej oka (`SoDepthBuffer.range` = 0..0.9999), żeby na
  wspólnej krawędzi jego linia przykrywała czarną krawędź modelu. Nowy szkic z
  Extract boundary edges jest od razu zaznaczony (cały, więc czerwony).
- **Zaznaczanie linii** (`ui/picking.py`), jak w Blenderze: klik = ta linia,
  Shift+klik = dodaj linię (ponownie: odejmij), Ctrl+klik = dodaj najkrótszą drogę
  od ostatniej linii do klikniętej (`geometry.line_path`, Dijkstra po końcach linii,
  od wolnego końca łańcucha), Alt+klik = cała pętla linii, zaczynając od klikniętej
  (`geometry.line_loop`), a Shift+Alt dokłada pętlę. Kolejność kliknięć
  zapamiętuje sam FreeCAD (`getSelectionEx` zwraca podelementy w kolejności
  zaznaczania). FreeCAD sam czyści zaznaczenie przy zwykłym i Shift-kliku, a dodaje
  przy Ctrl-kliku. Filtr zdarzeń na widoku 3D zapamiętuje modyfikatory kliknięcia,
  a obserwator zaznaczenia zaraz po FreeCADzie układa zaznaczenie od nowa.
  Modyfikatory działają tylko w trakcie kliknięcia (do końca obsługi puszczenia
  przycisku), więc zaznaczenia z kodu ich nie dziedziczą. Linia szkicu ma
  pierwszeństwo przed modelem: FreeCAD bierze tylko pierwszy obiekt na promieniu,
  a krawędź woli od ściany tylko w obrębie jednego obiektu, więc klik na wspólną
  krawędź często daje ścianę modelu. Obserwator sprawdza wtedy (`getObjectsInfo`
  w promieniu kliknięcia), czy pod kursorem jest linia szkicu, i przenosi na nią
  zaznaczenie. Uwaga: na niektórych pulpitach Linuxa Alt+klik przejmuje menedżer
  okien (przesuwanie okna).
- **Kierunek** (`ui/direction.py`): każda zaznaczona linia ma w połowie długości
  strzałkę (stożek leżący na płaszczyźnie szkicu, stały rozmiar na ekranie przez
  `SoShapeScale` FreeCADa), która pokazuje, w którą stronę pojedzie narzędzie
  (`geometry.line_runs` / `line_arrows`). Zwykły klik w strzałkę odwraca **cały
  łańcuch**, do którego należy linia, i nie dochodzi do FreeCADa, więc zaznaczenie
  zostaje. Klik z Shift/Ctrl/Alt przechodzi do zwykłego zaznaczania, a żeby zaznaczyć
  samą zaznaczoną już linię, klika się ją z dala od strzałki. Strzałka pod myszą jest
  żółta, a ściana pod nią nie jest wtedy podświetlana. Odwrócenie jest pamiętane przy
  liniach, dopóki są zaznaczone: łańcuch jest odwrócony, gdy którakolwiek jego linia
  ma znacznik, więc dołożenie linii Shiftem go nie gubi, a linia zaznaczona od nowa
  jedzie zgodnie z kolejnością kliknięć. Odwrócony łańcuch to ten sam łańcuch
  przejechany od końca (`chain_order(..., backwards)`); pojedyncza linia jedzie wtedy
  od końca do początku, a zamknięty okrąg w drugą stronę (G2 ↔ G3) z tego samego
  punktu (`_turned_round`). Strzałki siedzą w grafie sceny szkicu (za jego
  placement), są niewybieralne (`SoPickStyle`), a trafienie kliknięciem liczy
  `direction.arrow_at` z `getPointOnScreen`. Zaznaczenie całego szkicu (np. z listy)
  pokazuje strzałki na wszystkich liniach; FreeCAD maluje je wtedy kolorem
  zaznaczenia. Pułapka: obserwator widoku nie może czytać `vp.Object` w
  `slotChangedObject`, bo FreeCAD zgłasza Visibility jeszcze w trakcie budowy view
  providera (segfault przy otwieraniu pliku).
- **Contour tooling** (`freecad_cam.add_contour`): działa **tylko na zaznaczonych
  liniach**, w kolejności kliknięć. Zaczyna na pierwszej klikniętej linii (od jej
  końca odległego od drugiej) i kończy na ostatniej, chyba że łańcuch odwrócono
  strzałką (`backwards`; obiekt pomocniczy ma wtedy `Reversed`). Linie, które się nie stykają,
  są kolejnymi łańcuchami (podjazd między nimi). Cały zaznaczony szkic (np. kliknięty
  na liście) = wszystkie linie. Narzędzie jedzie po liniach (albo obok nich, patrz
  kompensacja niżej) od **Start Z** do **Z-Depth** (jednym przejazdem albo
  przejściami, patrz niżej). **Relative** (decyzja usera 2026-10-29, ptaszek pod Z-Depth w oknie
  i w Details, `Contour.relative`, `Contour.base_mm`, `ui/contour_relative.py`): zaznaczony
  (domyślnie; stare pliki bez pola tak samo) = obie wartości od **Z linii** (płaszczyzna ich
  szkicu od zera mocowania), każda linia od swojego Z, więc Z-Depth −1 tnie 1 mm pod każdą
  linią; odznaczony = od **punktu zerowego** mocowania niezależnie od wysokości linii, więc
  Z-Depth −10 tnie na Z−10 wszystkie. Obok ptaszka szara notka, co teraz znaczy, a podpowiedzi
  Start Z i Z-Depth idą za nim. Okno pamięta ostatni wybór (`LastContourRelative`, razem z
  ostatnim Z-Depth/Start Z, bo bez niego te liczby znaczyłyby co innego); przełączenie
  nie przelicza wpisanych wartości. Obie wartości mogą
  być **nad bazą albo pod nią** (decyzja usera 2026-10-20, „frezowanie ponad Z0”):
  Z-Depth −3 = 3 mm pod bazą, +2 = kończy 2 mm nad nią; Start Z = góra
  materiału (domyślnie 0 = przy Relative płaszczyzna szkicu, stare pliki bez pola tak samo),
  kroki Z idą od Start Z w dół. Model wymaga Start Z ≥ Z-Depth (komunikat); oba
  równe (decyzja usera 2026-10-21) = jeden przejazd na tej wysokości, np. gratowanie
  po Z0 (bez kroków Z i bez naddatku Z).
  Wysokość bezpieczna = 2 mm nad wyższym z: góra półfabrykatu / Start Z. Tłumacz robi z tego operację **Engrave** FreeCADa na obiektach
  pomocniczych `ContourLines` (`geometry.ContourLines`, Part::FeaturePython z
  linkiem do szkicu i listą `Edges`), po jednym na łańcuch, bo Engrave sortuje
  druty jednego kształtu po położeniu i zgubiłby kolejność. Krawędzie są budowane
  od nowa w kierunku jazdy (`_directed`), bo Engrave zaczyna drut od pierwszego
  wierzchołka pierwszej krawędzi. Obiekty pomocnicze śledzą zmiany szkicu i są
  przesunięte do układu mocowania: StartDepth = baza + Start Z, FinalDepth =
  baza + Z-Depth (baza = płaszczyzna przy Relative, inaczej 0), StepDown = krok Z (0 = bez kroków), a wyrażenia SetupSheet są
  zdjęte. Ścieżkę robi proxy `engine/contour.Contour` (podklasa Engrave FreeCADa, jak
  wiercenie): cięcia w kolejności przejść, łańcuch po łańcuchu (`freecad_cam.contour_cuts`).
  **Start contour / End contour** (prośba usera 2026-10-29, pod Advanced, osobne moduły
  `engine/contour_ends.py` + `ui/contour_ends.py`): pola `start_extend_mm`/`end_extend_mm`
  modelu Contour. Dodatnie = cięcie dłuższe o tyle przed pierwszą / za ostatnią linią,
  prosto wzdłuż ich stycznej (zdjęcie stocka za narożnikiem; prosta linia jest po prostu
  przedłużona, łuk dostaje odcinek); ujemne = krótsze, mierzone wzdłuż linii (start w
  połowie linii, fazownik schodzi przed ścianą). Zmiana działa na liniach PROGRAMU w
  `geometry.contour_runs` przed przejściami XY, kompensacją i łukami dojazdu, więc RL/RR i
  łuki idą za nowymi końcami. Tylko otwarte łańcuchy: zamknięta pętla daje ProjectError
  (mój wybór, nakładka pętli do decyzji usera). Z odznaczonym Advanced pola są ukryte i = 0;
  kontur z nimi otwiera się z Advanced (`contour_advanced.needs_advanced`). Obiekt
  pomocniczy ContourLines ma StartExtend/EndExtend (rysunek w 3D).
  **Kilka szkiców w jednym konturze** (prośba usera 2026-10-29, kilka Extract boundary
  edges, `add_contour_sketches`): linie zaznaczone na kilku szkicach (Shift+klik) dają
  jeden kontur, szkic po szkicu w kolejności pierwszego kliknięcia (FreeCAD grupuje
  zaznaczenie po obiektach, więc przeplatanie linii dwóch szkiców nie jest pamiętane).
  Każdy `ContourLines` ma własny szkic i własne położenie, więc przy Relative **Start Z i
  Z-Depth liczą się od płaszczyzny własnego szkicu** (ściany na różnych wysokościach), bez
  Relative od zera, czyli dla wszystkich tak samo. Link
  operacji (`AvangardeSketch`) = pierwszy szkic; StartDepth = baza najwyższej płaszczyzny + Start Z,
  FinalDepth = baza najniższej + Z-Depth (`contour_planes`, `contour_sketches`); wysokość
  bezpieczna od wyższego z: StartDepth / najwyższa płaszczyzna. Linie na różnych wysokościach
  (różne szkice = różne łańcuchy) narzędzie robi **każdą osobno, z wyjazdem i wjazdem**
  (decyzja usera 2026-10-29: bez schodka ani rampy między nimi). Szkice muszą
  pasować do jednego mocowania. Details konturu: **Lines at** = Z płaszczyzn od zera.
  Kontury sprzed przejść (zwykłe Engrave) dostają tę klasę przy przeliczeniu. Wartości
  użytkownika zapisuje JSON `AvangardeOperation` (`model/operations.py`) i link
  `AvangardeSketch`. Zmiana zera, Start Z albo Z-Depth przelicza położenie i głębokości.
  Kontury z etapu 3 (na Draft clone całego szkicu) dalej działają. Uwaga: nazwy
  linii („Edge3”) to numeracja kształtu szkicu; po edycji szkicu (przyszły
  Sketcher) mogą się przesunąć.
- **Kompensacja (korekcja) narzędzia** (menu Compensation w oknie Contour tooling i
  w Details, `Contour.compensation`): Off = środek narzędzia na liniach, Left (RL) /
  Right (RR) = narzędzie z lewej / prawej strony linii patrząc wzdłuż strzałek.
  Wtedy program ma **same linie z RL/RR**, a sterowanie odsuwa narzędzie o promień
  z tabeli narzędzi.
- **Sposób dojazdu** (menu Approach, `Contour.approach`, decyzje usera):
  - **Arc** (domyślny w oknie): zjazd w Z w środku łuku stycznego do początku linii,
    prosta do początku łuku, 45° łuku na linie, na końcu to samo wstecz i prosta z
    powrotem do środka łuku (`model/leads.py`, jak programy warsztatu). Z kompensacją łuk
    leży po stronie narzędzia, prosta do łuku włącza RL/RR, prosta z powrotem R0.
    Bez kompensacji to samo jedzie **środek narzędzia**, łuk po stronie
    `Contour.arc_side` (lewa/prawa wzdłuż strzałek; stare pliki: lewa; odwrócenie
    strzałek zmienia stronę). Pole **Approach radius**
    (`lead_radius_mm`): domyślnie promień narzędzia + 0,5 mm (`LEAD_CLEARANCE_MM`),
    czyli zjazd 0,5 mm obok konturu. Programy warsztatu biorą 1,1 × promień (sprawdzone na
    dwóch próbkach: Ø12 → 6,6, Ø8 → 4,4). Z kompensacją promień musi być większy od
    promienia narzędzia (TNC: łuk skorygowany o promień musi mieć promień > 0).
    `None` w pliku = domyślny, który idzie za narzędziem; okno zapisuje wpisaną wartość.
  - **None**: zjazd w Z na początku linii. Z kompensacją RL/RR włącza się na ruchu
    szybkim w XY nad produktem (`L X… Y… RL FMAX`), ruchy w Z idą bez R0 (`L Z+20.
    FMAX M3 M8`), po konturze narzędzie wychodzi w górę z kompensacją i dopiero
    nad produktem wyłącza ją ruchem w XY na ostatni punkt (`L Z+40. FMAX`, `L X… Y…
    R0 FMAX`). Między łańcuchami jednej operacji też: góra, R0, RL nad nowym startem.
    Bez kompensacji: jak dawniej (pliki sprzed kompensacji mają `approach = none`).
  - Zamknięty łańcuch z kompensacją albo łukiem zaczyna i kończy się **w połowie
    swojej pierwszej linii** (zjazd i łuki z dala od narożników).
  - **Advanced** (decyzja usera 2026-10-21, `ui/contour_advanced.py`, w oknie i w
    Details): ptaszek „Advanced” na końcu formularza pokazuje **Contour side**
    (`arc_side`) i dodaje do menu Compensation **Off with arc** (środek narzędzia na
    liniach, łuki dojazdu po wybranej stronie). Zwykłe **Off** = zawsze prosto w dół
    na linie (menu Approach zablokowane na None); Off with arc = OFF + ARC w modelu
    (Approach zablokowane na Arc); menu Approach jest otwarte tylko dla RL/RR i
    pamięta tamten wybór. Kontur OFF + ARC (też ze starych plików) otwiera się z
    zaznaczonym Advanced. Odznaczenie Advanced przy Off with arc = Off.
    Contour side = strona narzędzia (decyzja usera 2026-10-21): przy RL/RR to samo co
    kompensacja (wybór jednego przestawia drugie; przy M3 lewa = współbieżnie/climb,
    prawa = przeciwbieżnie), bez kompensacji strona łuków i **XY offsetu**.
  - **XY offset bez kompensacji** (decyzja usera 2026-10-21, pod fazowanie
    afbraamfreesem: kontrola wielkości fazki): przy Off i Off with arc pole XY offset
    jest otwarte tylko z Advanced (tam jest strona); środek narzędzia jedzie tyle obok
    linii po stronie konturu (ujemny: po drugiej), jednym przejazdem (XY width / Finish
    XY nadal wymagają RL/RR). Zamknięta pętla z offsetem zaczyna się w połowie pierwszej
    linii (jak z kompensacją), łuki dojazdu dochodzą do przesuniętych linii. Program =
    ścieżka środka (offset OCCT, łuki na narożnikach zewnętrznych).
  - Okno pamięta ostatni wybór (`LastContourCompensation` — jak pokazane w menu, też
    `off_arc`; `LastContourApproach` — dla RL/RR; `LastContourAdvanced`,
    `LastContourArcSide`). Off with arc wraca tylko z zapamiętanym Advanced.
  - Ścieżka FreeCADa (widok 3D, symulacja) to **gdzie naprawdę jedzie środek
    narzędzia**: obiekt `ContourLines` (właściwości `Compensation`, `ToolRadius`,
    `Approach`, `LeadRadius`, `ArcSide`) buduje środek z `geometry.contour_runs` (`Run`: krawędzie
    programu i środka narzędzia, strona, łuki tak/nie). Z kompensacją to offset 2D z
    OCCT (`makeOffset2D`, łuki na narożnikach zewnętrznych, przecięcie na
    wewnętrznych, jak TNC), a łuki dojazdu są mniejsze o promień wokół tych samych
    środków. OCCT nie zna płaszczyzny pojedynczej prostej (ani linii na jednej
    prostej), więc takie linie i pojedynczy łuk przesuwa sam `_offset`.
  - Program (`freecad_cam.nc_moves` → `_programmed`, tylko z kompensacją): każde
    cięcie ścieżki (od zjazdu do najbliższego ruchu szybkiego) zastępują krawędzie
    programu tego `Run`, którego środek narzędzia zaczyna i kończy się tam gdzie
    ono, na głębokości i z posuwem z FreeCADa. Bez łuków także ruchy szybkie nad
    startem i zjazd idą na punkt programu z kompensacją, a przed ruchem do innego
    startu dochodzi ruch z R0. Ruchy mają `nc.Move.compensation`. Dopasowanie po
    punktach, a nie po kolejności, bo Engrave sortuje druty jednego kształtu (cały
    szkic = jeden obiekt pomocniczy z kilkoma łańcuchami).
  - Narzędzie, które się nie mieści (np. frez 8 mm w otworze 6 mm, odsunięcie
    pustoszeje), albo za mały promień dojazdu daje czytelny błąd **przed** zmianą
    (`_check_fit` w `add_contour` i `set_contour`). Zamiana wariantu narzędzia
    (`replace_tool`) przelicza kontury z nowym promieniem.
  - Pułapka: `makeOffset2D` przy braku miejsca rzuca `Base.CADKernelError`, a nie
    `Part.OCCError`.
- **Przejścia (passes)** (decyzje usera, `model/operations.Contour`, pola w oknie i w
  Details, `ui/contour_passes.py`): do dokładnego wykończenia (naddatek 0,1 mm przed
  ostatnim cięciem), wycinania z dużego kawałka jednym poleceniem i pasowań (przejście
  za linię).
  - **Z step** (`z_step_mm`, 0 / None = cała głębokość naraz): **pełne kroki, reszta na
    końcu** (jak TNC; −10 krokiem 4 = −4, −8, −10).
  - **XY width** (`xy_width_mm`, materiał z boku linii po stronie narzędzia, liczony od
    linii) i **XY step** (`xy_step_mm`): szerokość dzielona na **równe** przejścia nie
    szersze od kroku (10 mm krokiem 4 = 3 po 3,33), od zewnątrz do linii. Krok szerszy od
    średnicy narzędzia to błąd (zostawiłby materiał).
  - **Finish Z / Finish XY** (naddatek wykańczający): przejścia zgrubne stają tyle nad
    dnem / od ściany, ostatni poziom Z zbiera dno, a ostatnie przejście XY ścianę, **też
    krokami Z** (decyzja usera). Przejście wykańczające jest zawsze ostatnie.
  - **XY offset** (`offset_xy_mm`): ostatnie przejście tyle obok linii; **ujemny = za
    linię**, w materiał detalu (pasowania z tolerancją, np. −0,02).
  - **Order**: przejścia zgrubne **domyślnie przejściami XY** (każde XY na wszystkie
    poziomy, potem następne bliżej linii), albo poziomami (na każdym Z wszystkie XY).
  - Przejścia XY, naddatek XY i offset wymagają **kompensacji Left/Right** (bez niej nie
    wiadomo, po której stronie jest materiał); bez kompensacji pola XY są wyłączone.
  - Każde przejście XY to linie **programu przesunięte** o swój offset (`contour_runs(...,
    offsets)`, OCCT: łuki na narożnikach zewnętrznych), z RL/RR; środek narzędzia to
    offset **linii programu** o promień (tak liczy TNC, więc przy ujemnym offsecie narożnik
    zostaje ostry, a łuk ma promień narzędzia). Dojazd po łuku liczony od linii przejścia.
  - Między cięciami narzędzie idzie w górę na 2 mm nad półfabrykat (powrót na start
    linii otwartej idzie nad produktem), potem szybko na 2 mm nad poziom, który to samo
    przejście już wycięło (tam narzędzie już było), dalej posuwem Z. Zjazd przejść
    wewnętrznych (środek łuku) częściowo wchodzi w materiał, który zostawiło przejście
    zewnętrzne (tak jak w innych CAM-ach przy dojeździe z boku).
  - `_programmed` dopasowuje cięcia ścieżki do przejść po punktach, każde przejście tyle
    razy, ile ma poziomów. Limit 5000 cięć na kontur.
- **Linie szkicu muszą leżeć w poprzek narzędzia** mocowania (`contour_fits`): szkic
  skierowany do frezu (`sketch_fits`) **albo od niego** (`sketch_faces_away`, prośba usera
  2026-10-29: kontur po obrysie ściany spodu detalu w mocowaniu od góry). Szkic nie ma
  własnego zera, więc taki szkic to po prostu linie na swoim Z (np. Z−15). Żeby lewa/prawa
  (RL/RR, strona łuków, XY offset) była taka, jak widzi ją frez, `ContourLines` ma `Flipped`
  (ustawiane w `_sync_contour`, też po zmianie zera), a linie są liczone w układzie szkicu
  obróconego o 180° wokół jego X (`geometry.facing_tool`, `contour_chains(..., flipped)`);
  położenie obiektu pomocniczego = zero⁻¹ · szkic · obrót. Kolejność linii i strzałki są
  w 3D, więc się nie zmieniają. Okno wybiera najpierw mocowania, do których szkic jest
  skierowany (`setups_for_contour`). Details szkicu: Setups z dopiskiem „from the other
  side: contours only”. Wiercenie, gwinty i helix nadal wymagają szkicu skierowanego do
  frezu (góra otworu = płaszczyzna szkicu). Szkic ze ściany bocznej (linie wzdłuż osi
  narzędzia) jest odrzucany. Jeśli żadne mocowanie nie pasuje, program każe najpierw zrobić
  Snap-0-Point na tej ścianie. Testy: `tests/test_contour_from_below.py` (strona RL i łuków
  sprawdzona mutacją), `tests_gui/test_contour_from_below.py`.
- **Narzędzie** (`ui/contour_dialog.py`): lista narzędzi mocowania albo dowolny
  wariant z tabeli narzędzi przez **Choose tool...** (`ToolLibraryDialog(pick=True)`:
  ta sama tabela z filtrem materiału i wyszukiwaniem, wybór jednego wiersza, także
  narzędzia już w mocowaniu). Wariant spoza mocowania dochodzi do niego przy OK
  (`freecad_cam.library_tool`); inny wariant numeru T, który mocowanie już ma,
  zastępuje go (okno wyboru pyta, a podpowiedź pod listą to mówi). Okno startuje z
  narzędziem użytym ostatnio (`LastContourTool`, ID wariantu), a bez niego z
  pierwszym narzędziem mocowania, które nie jest wiertłem; gdy nic nie ma, każe
  wybrać (warianty różnią się obrotami i posuwami, więc program sam nie wybiera).
  Domyślny promień dojazdu idzie za średnicą wybranego narzędzia.
- **Zmiana narzędzia konturu**: Details > **Change tool...** (`handlers.change_contour_tool`,
  `freecad_cam.set_contour_tool`): to samo okno wyboru, sprawdzenie, czy narzędzie
  się mieści (kompensacja, promień dojazdu użytkownika), domyślny promień dojazdu
  idzie za nowym narzędziem. Stare narzędzie zostaje w mocowaniu.
- **Pułapka FreeCADa (GUI): cofnięcie utworzenia narzędzia jest zepsute.** Gdy
  transakcja tworzy ToolBit (z bryłą PartDesign) i obiekt, który do niego linkuje,
  cofnięcie w GUI usuwa ToolBit i na tym się zatrzymuje: ToolController zostaje bez
  narzędzia, a reszta kroku (np. link operacji) się nie cofa. W FreeCADCmd działa,
  w czystym FreeCADzie (workbench Part/CAM) też jest zepsute. Dlatego narzędzia
  powstają **poza transakcją** (`handlers._tool_controller` przed `openTransaction`,
  Tool library bez kroku cofania): undo cofa operację, a narzędzia dodaje się i
  usuwa tylko na liście narzędzi („Remove from project”).
- **Pułapka FreeCADa (GUI): nowe narzędzie gubi zaznaczenie linii.** ToolBit robi
  bryłę w ukrytym dokumencie i kopiuje ją do projektu; potem szkic wczytany z pliku,
  którego linie były zaznaczone, jest zaznaczony cały (strzałki na wszystkich
  liniach). `handlers._tool_controller` zapamiętuje zaznaczenie przed narzędziem z
  biblioteki i przywraca je w kolejności kliknięć, więc po OK zaznaczone zostają
  linie operacji (test `tests_gui/test_selection_kept.py`).
- Planowane: okrojony Sketcher do rysowania (przyciski grupy Draw uruchamiające narzędzia
  Sketchera).

## Deburring (fazowanie krawędzi)

Prośba usera 2026-10-30, zrobione 2026-11-02 (`model/deburring.py`, `engine/deburring.py`,
`ui/deburring.py`, testy `tests/test_deburring.py`, `tests_gui/test_deburring.py`, obrazek
`Resources/images/deburring_start.svg`). CAM > **Deburring** (wstążka, Milling; dawny
przycisk-zaślepka „Chamfer”) i **Deburring...** w Details szkicu: fazownik po zaznaczonych
liniach szkicu, dokładnie jak Contour tooling (kolejność kliknięć, strzałki, linie kilku
szkiców, każdy od swojej płaszczyzny), ale **bez kompensacji**.

- **Rachunek** (`model/deburring`): fazka c = szerokość na ścianie linii (przy 90° obie
  przyprostokątne), Tip below chamfer e = ile czubek schodzi pod fazkę, stożek: promień czubka r,
  tg połowy kąta t. Czubek na **c/t + e** pod liniami, środek **r + e·t** obok nich (nie zależy
  od fazki: większa fazka = ten sam tor, głębiej). Krawędź czubka zostaje e·t od ściany pod fazką.
  Sprawdzane (`check`): narzędzie Chamfer/VBit z kątem, stożek na wysokości ściany ≤ średnica
  (komunikat z największą możliwą fazką), środek ≥ promień czubka (inaczej czubek w ścianie),
  fazka > 0. Wzorzec usera (detal testowy C, Contour 1/2: T29, XY offset 0,85, Z-Depth −1) =
  fazka 0,15 + czubek 0,85; Deburring z tymi wartościami daje identyczne cięcia.
- **Okno** (decyzje usera 2026-11-02): Chamfer + Tip below chamfer (domyślnie 0,5 / 0,5),
  **Side** w oknie (lewa/prawa po strzałkach; domyślnie lewa = współbieżnie przy M3),
  **Approach** None (domyślnie: łuk nie mieści się w małym otworze, np. Ø6,6 z T29) albo Arc
  z promieniem, **Advanced** = własne Z-Depth (czubek od linii) i XY offset (środek obok linii)
  jak w Contour tooling + Start/End contour; zaznaczenie Advanced wpisuje tam to, co wychodzi
  z fazki, a linia pod polami pokazuje wtedy, jaką fazkę to daje. Bez Advanced linia mówi, gdzie
  jedzie czubek i środek. Lista narzędzi z ptaszkiem „Chamfer mills only”. Okno pamięta
  ostatnie wartości (`LastDeburring`, JSON, bez promienia dojazdu) i narzędzie (`LastDeburringTool`).
- **Zapis**: operacja to zwykły kontur (`add_contour_sketches(..., name="Deburring")`,
  „Deburring 1”), więc ścieżka, program `.H`, Verify, Play i czas cyklu są konturu; w `.H`
  własny tytuł **„Deburring”** (`nc.DEBURRING`, decyzja usera 2026-11-02: łatwiej potem
  przetłumaczyć). Model Contour (`AvangardeOperation`) jest wyliczany z modelu Deburring zapisanego
  obok (`AvangardeDeburring`): OFF, jeden przejazd (Start Z 0, Relative), `offset_xy_mm` = środek,
  `arc_side` = strona. Zaczepy we wspólnym kodzie (jak Facing/Slot/Helix): `set_tool` i
  `change_operation` najpierw pytają `engine.deburring`, `_sync_operations` przelicza kontur z
  narzędzia (`follow_tool`: inny wariant numeru T, np. inny czubek), handlers `change_tool` /
  `edit_operation` i Details w `project_panel` wybierają Deburring przed konturem.
- **Pętle na materiale** (decyzja usera 2026-11-02: strona zostaje po strzałkach, ale z
  ostrzeżeniem, które można pominąć): Extract boundary edges **nie** układa pętli w stałym
  kierunku (mostek demonstracyjny: obrys i otwory w tę samą stronę, więc „wszystkie linie, lewa” fazuje obrys od
  środka = rowek w wierzchu; detal testowy C akurat dobrze). `on_material`: ściana z zamkniętych
  drutów szkicu (`FaceMakerBullseye`, otwory wycięte) w układzie przebiegów (`facing_tool`),
  pętla jest „na materiale”, gdy ponad połowa długości toru środka (środki krawędzi) leży na ścianie.
  OK w oknie (nowe i Edit...) pyta „Deburr anyway?” (Nie = okno zostaje, ostrzeżenie pod polami),
  Details pokazują czerwoną notkę pod „Lines at”. Otwarte linie nie są sprawdzane.
- **Łuk dojazdu, który się nie mieści** (decyzja usera 2026-11-02: ostrzeżenie, nie odmowa;
  `engine/lead_check.py`, `ui/lead_warning.py`): bez kompensacji środek freza jedzie samym łukiem,
  więc w małym otworze (domyślny promień 3,5 w torze 1,4–2,5) łuk zawija za tor w stronę krawędzi:
  fazka miejscowo rośnie, a przy 0 mm frez przecina linie. `too_close` próbkuje prostą i łuk wjazdu
  i wyjazdu (24 punkty na krawędź) i mierzy odległość środka od linii szkicu (wszystkich, w układzie
  przebiegów); ostrzega, gdy jest mniejsza niż XY offset − 0,01 mm. Dotyczy Deburringu i
  Contour tooling przy Off with arc z XY offsetem > 0 (`checked`); RL/RR i zwykłe Off nie.
  Deburring: w tym samym pytaniu „Deburr anyway?” i notce co pętle na materiale; Contour tooling:
  OK w oknie (nowe i Edit...) pyta „Go on anyway?” (`lead_warning.go_on`, Nie = okno zostaje,
  ostrzeżenie pod polami), Details konturu pokazują czerwoną notkę pod „Lines at”
  (`AvangardeCamContourLeadWarning`). Mostek z T29, łuk 3,5: środek 0,014 mm od krawędzi otworów.

## Wiercenie (Drilling)

Decyzje usera: otwory wskazuje się na dwa sposoby (okręgi w szkicu albo otwory
klikane w modelu 3D), jeden uniwersalny cykl **CYCL DEF 205** (TNC: uniwersalne
wiercenie z wycofaniem), w programie `.H` cykl + `CYCL CALL POS` na każdy otwór,
głębokość do czubka albo do pełnej średnicy (przełącznik w oknie).

- **Model** (`model/operations.Drilling`): głębokość ujemna od góry otworów (płaszczyzna
  szkicu), jak Z-Depth konturu, `depth_to` = `TIP` (czubek) albo `FULL_DIAMETER` (część
  walcowa; czubek idzie głębiej o długość stożka, `tools.tip_length_mm`: ½·Ø / tan(½·kąt),
  dla 118° ok. 0,3 × Ø, dla 180° zero). Głębokość do pełnej średnicy liczy CAM (Q201 do
  czubka, Q395 = 0), bo Q395 = 1 wymaga kąta wiertła w tabeli narzędzi maszyny. Reszta pól
  to parametry cyklu 205 w jego kolejności: Q202 krok (None = cała głębokość naraz), Q212
  zmniejszanie kroku i Q205 najmniejszy krok, Q258/Q259 odstęp zatrzymania górny/dolny,
  Q257 głębokość łamania wióra i Q256 cofnięcie (0 = bez łamania), Q211 postój na dnie,
  Q379 pogłębiony punkt startu, Q200 odstęp bezpieczeństwa (2 mm) i Q204 drugi odstęp
  (50 mm, nad nim narzędzie jedzie od otworu do otworu i na nim kończy). Domyślne wartości
  jak w próbce warsztatu (`Wiercenie.H` usera): Q258 = Q259 = Q256 = 0,2; Q202 = 1 mm i
  Q257 = 4 mm (decyzja usera). Posuwy liczy
  tłumacz: **Q206 (posuw roboczy w dół) = posuw „XY” narzędzia z tabeli, czyli jego posuw
  roboczy, Q253 = posuw Z** (tak robią programy warsztatu: T42 Alu ma XY 500 i Z 375, w próbce
  Q206=500, Q253=375; wiertło w XY jeździ tylko szybko).
- **Tłumacz** (`freecad_cam.add_drilling`, `set_drilling`, `set_tool`): operacja
  Drilling FreeCADa na obiekcie pomocniczym `HoleCircles` (`geometry.HoleCircles`, link do
  szkicu i lista okręgów `Edges`, przesunięty do układu mocowania jak `ContourLines`).
  Wierci **w kolejności kliknięć**: FreeCAD sam sortuje otwory
  (`PathUtils.sort_locations`) i wierci wszystkie między StartDepth a FinalDepth
  operacji, więc proxy operacji to `engine/drilling.Drilling` (podklasa `ObjectDrilling`
  FreeCADa), która robi ścieżkę sama: otwory w kolejności cech Base, **każdy od swojej
  góry do swojej głębokości** (`freecad_cam.drill_moves`, płaszczyzna R = góra otworu +
  Q200), cykle generatora FreeCADa. Bez klikniętych okręgów: wszystkie okręgi szkicu, w
  kolejności FreeCADa ustalonej przy tworzeniu. Otwór to pełny okrąg albo łuki jednego
  okręgu (ten sam środek i promień) zamykające go dookoła — szkic ściany z modelu STEP ma
  otwory z dwóch połówek (`geometry._sketch_holes`); otwór nosi nazwę swojej pierwszej
  linii, klik w dowolny jego łuk wybiera go raz, a operacja wierci pełny okrąg. Linia
  albo samotny łuk to czytelny błąd.
- **Otwory klikane w modelu** (`freecad_cam.add_model_drilling`, `geometry.model_hole`):
  klik w ściankę otworu albo jego okrągłą krawędź (Shift+klik dodaje następny, ponownie:
  odejmuje), w kolejności kliknięć. Otwór to cały walec: ściany o tej samej osi i
  promieniu, które się stykają (STEP często dzieli walec na połówki). Odrzucane z
  komunikatem: ściana bez materiału dookoła (zaokrąglony narożnik, łuk, koniec rowka;
  sprawdzane próbkami na obwodzie), czop (materiał w środku), otwór nie wzdłuż osi
  narzędzia mocowania, otwór zamknięty od strony narzędzia. Góra otworu = najwyższy punkt
  walca (pod pogłębieniem: jego dno), w programie Z `CYCL CALL POS`. Otwór jest
  **przelotowy**, gdy tuż pod walcem nie ma materiału (próbki pod dnem przy ściance i na
  osi); dno, stopień do mniejszego otworu albo stożek wiertła (współosiowy stożek zwężający
  się w dół) = nieprzelotowy. Obiekt pomocniczy `ModelHoles` (link `Model` do oryginału,
  lista `Holes` z jednym klikniętym elementem na otwór, Placement = odwrotność zera
  mocowania) ma kształt z okręgów gór otworów w układzie mocowania, więc FreeCAD czyta
  z niego położenie i średnicę jak z `HoleCircles`. Otwory liczy od nowa przy każdym
  przeliczeniu (`drill_targets`), więc idą za zmianą zera. Wiercenie idzie w aktywnym
  mocowaniu, jeśli jego narzędzie sięga otworów, inaczej w pierwszym, które sięga.
- **Szybkość rozpoznawania otworów** (2026-10-23, płyta testowa A, płyta 147 ścian):
  ~30 próbek `Shape.isInside` na otwór, każda ~6 ms (OCC buduje klasyfikator bryły od zera
  przy każdym wywołaniu), a ten sam otwór był liczony 5–6 razy przy jednym wierceniu
  (klik, silnik, `ModelHoles.execute`, `drill_targets` przy każdym przeliczeniu): 5 otworów
  = 6,5 s. `geometry.model_hole` pamięta wynik `_recognise_hole` dla tego samego kształtu
  (hashCode + `isSame`; wpis trzyma kształt, więc jego adresu nie zajmie inny), elementu i
  osi narzędzia, max 512 wpisów; odrzucenia nie są pamiętane. Teraz 1,1 s (raz, przy
  kliknięciu), dodanie operacji 0,025 s. numpy nic by nie dał: czas jest w C++ OCC, nie w
  rachunkach Pythona.
- **Głębokość z modelu** (decyzja usera, `Drilling.depth_mm = None`, przełącznik
  **From the model**, domyślnie włączony dla otworów modelu): pełna średnica wiertła do
  końca walca otworu (nieprzelotowy), a w przelotowym wychodzi pod spód o `through_mm`
  (pole **Out under through holes**, domyślnie 1 mm); czubek idzie głębiej o stożek.
  Wyłączony: jedna głębokość wpisana przez użytkownika, od góry każdego otworu, jak przy
  szkicu. Okręgi szkicu nie mają własnej głębokości (głębokość z modelu odrzucana).
- Ścieżka FreeCADa (widok 3D, symulacja) pokazuje cykl tak, jak FreeCAD umie: G83 przy
  wycofywaniu (krok krótszy od otworu), inaczej G73 przy łamaniu wióra albo G82 z postojem,
  inaczej G81; StartDepth = najwyższa góra otworów (płaszczyzna szkicu), FinalDepth =
  najgłębszy czubek, RetractHeight = Q200 nad górą, SafeHeight = ClearanceHeight = Q204
  nad najwyższą górą (program przychodzi do pierwszego otworu z wymiany narzędzia). FreeCAD nie umie wycofywania i
  postoju w jednym otworze (taki otwór po cichu pomija!), więc wtedy ścieżka tylko
  wycofuje; zmniejszania kroku i odstępów zatrzymania nie pokazuje. Program dostanie
  pełny cykl 205.
- Zmiana zera, półfabrykatu albo narzędzia (`_sync_operations`) przelicza wiercenie (długość
  stożka idzie za wiertłem).
- Program (`freecad_cam._drill_cycle` → `nc.DrillCycle`, `post/heidenhain._drilling`): jak
  w próbce warsztatu, sprawdzone testem złotym bajt w bajt (`tests/test_post.py`, poza
  linią 4, gdzie CAM warsztatu wpisuje ścieżkę swojego pliku projektu, i tytułem): tytuł po
  angielsku `*- Deep Drilling With Chip Breaking` (decyzja usera, interfejs jest po
  angielsku; w programach warsztatu: `*- Diepboren met Spaanlossen`), wywołanie wiertła w innym formacie niż frezu (`  * -TOOL#: 42 Diameter:
  Ø+10.2 -- nazwa`, `TOOL CALL 42 Z S2185 DL0 DR0;` bez nazwy), **bez** `FN0: Q30/Q31`,
  dojazdu `L Z+20 M3 M8` i odjazdu `Z+40`: `CYCL DEF 205 UNIVERSEELBOREN` i `CYCL CALL POS
  X… Y… Z0 FMAX` na każdy otwór, wrzeciono i chłodziwo (`M3 M8`) na pierwszym. Linie Q
  cyklu 205 nie mają numerów (linia Q339 cyklu 247 ma), po wartości stała liczba spacji na
  każdą linię (jak w próbce), formaty liczb jak w próbce (`Q200=2`, `Q201=-30.`,
  `Q211=0.`, `Q379=+0`). Decyzja usera: **Q203 = 0**, a góra otworów (płaszczyzna szkicu w
  układzie mocowania) idzie w Z `CYCL CALL POS` (TNC dodaje je do Q203; `Z0`, `Z-5`).
  Q253 na sterowaniu to „AANZET VOORPOS.” (posuw pozycjonowania), posuwu wycofania Q208
  programy warsztatu nie piszą. Głębokość Q201 do czubka, Q202 bez kroku = cała
  głębokość. Bez półfabrykatu (`nc.Setup.stock = None`) nie ma `BLK FORM`, jak w próbce.
  Każdy otwór (`nc.DrillHole`) ma swoją górę (Z `CYCL CALL POS`) i głębokość Q201;
  otwory modelu o innej głębokości dostają ponownie `CYCL DEF 205` z nową Q201 (i Q202,
  gdy wierci całą głębokość naraz).
- **Okno** (`ui/drilling_dialog.py`, CAM > Drilling albo Details szkicu > Drilling...,
  `handlers.drilling`): zaznaczone okręgi szkicu w kolejności kliknięć (Shift+klik dodaje),
  cały zaznaczony szkic = wszystkie okręgi, inne zaznaczone linie są pomijane (okno to
  mówi); albo otwory kliknięte w modelu (okręgi szkicu i otwory modelu naraz: komunikat).
  Nagłówek „Deep drilling with chip breaking (cycle 205)”, otwory (liczba i Ø w
  kolejności, przy modelu też „through” / „5 deep”), narzędzie (`ui/tool_choice.ToolChooser`,
  wspólne z konturem). **Podpowiedź wiertła** (decyzja usera, `suggested_drill`): wiertło
  o Ø większości otworów (±0,005 mm), najpierw z mocowania (ostatnio użyte pierwsze),
  potem z tabeli narzędzi w materiale ostatnio użytego wiertła albo narzędzi mocowania
  (albo jedyny wariant); gdy materiał niejasny, nic z tabeli (warianty mają inne obroty i
  posuwy). Bez podpowiedzi: ostatnio użyte do wiercenia (`LastDrillingTool`), inaczej
  pierwsze wiertło mocowania. Wiertło innej Ø niż otwory: pomarańczowe ostrzeżenie
  (`fit_text`), ale OK działa. Posuwy Q206 /
  Q253 z narzędzia (tylko do odczytu), pola cyklu (`DrillingFields`, etykiety z numerami Q):
  na wierzchu głębokość + Tip / Full diameter, Q202 (0 = cała głębokość naraz), Q257 (0 =
  bez łamania), Q256, Q211; pod zwijanym „Advanced” Q212, Q205, Q258, Q259, Q379, Q200,
  Q204. Pod spodem, jak głęboko pójdzie czubek. Okno pamięta ostatnie wartości
  (`LastDrilling`, JSON). Pola długości przyjmują każdą wartość, a model odrzuca złą z
  komunikatem (QuantitySpinBox po cichu przycina).
- **Details** (`details.DrillingView`): te same pola na żywo (wpisane po pauzie, Tip / Full
  i From the model od razu, każda zmiana jednym krokiem undo), przy modelu otwory z
  głębokościami i zakres gór, Change tool... (`handlers.change_tool`, wspólne z konturem,
  `freecad_cam.set_tool`), Remove operation.
- Pułapki: ponowny klik w zaznaczoną ścianę zaznacza w FreeCADzie **cały obiekt** (pusty
  podelement), więc Shift+klik szuka ściany pod kursorem (`picking._model_element_under`)
  i dopiero ją odejmuje. Po utworzeniu operacji FreeCAD zostawia zaznaczony cały model
  (cały czerwony), więc wiercenie z modelu czyści zaznaczenie. Ścieżka wiercenia (pionowa
  linia na osi) przykrywa na ekranie środek otworu: klik tam wybiera operację.

## Frezowanie gwintów (Thread milling)

Wzór: prawdziwy program warsztatu (gwint M3 frezem T216;
detal z numerem artykułu, **nie do repo**). Gwint wewnętrzny prawy, tak jak ten program go
pisze (`model/threads.py`):

- nad otwór w XY, `Z+20` z `M3 M8`, szybko na 2 mm nad górę otworu, posuwem Z (FQ30) na
  górę otworu (Z0), prosto od środka na promień **nominalny** z `RR` (`L X+r RR FQ31`),
  helisa w dół półobrotami zgodnie z ruchem wskazówek (`CC` + `CP IPA-180. IZ-P/2 DR-`),
  powrót do środka (`L X… R0`); każde kolejne przejście: szybko na górę otworu (`L Z+0.
  R0 FMAX`) i ta sama helisa jeszcze raz; między otworami 10 mm nad górą (`BETWEEN_MM`),
  po ostatnim `Z+40`.
- Decyzje usera: rozmiar gwintu z otworu + pole „Major diameter” (`threads.suggested_major`:
  Ø otworu + skok, gdy to rozmiar normowy o tym skoku, np. Ø2.5 + 0.5 = M3; albo Ø otworu,
  gdy sam jest rozmiarem normowym, np. okrąg narysowany na M3; inaczej Ø + skok; tabela
  `STANDARD`: M zwykłe i drobnozwojne, G). Skok zawsze z freza. Pole „Passes” = liczba
  **identycznych** przejść, domyślnie 2 jak w programie warsztatu. Głębokość, która nie jest
  wielokrotnością P/2: pełne półobroty i na końcu krótszy łuk (skok zostaje dokładny).
  Na razie tylko wewnętrzny prawy, z góry w dół, DR- z RR; lewe, zewnętrzne i od dołu
  później.
- Model: `operations.ThreadMilling(major_diameter_mm, depth_mm (ujemna od góry otworu),
  passes=2)`, `check(Ø freza, skok)`. `threads.moves(...)` daje ruchy `nc.Move` dla obu
  wersji: w programie promień nominalny z kompensacją RIGHT, w ścieżce FreeCADa środek
  narzędzia (promień nominalny − R freza, bez kompensacji).
- Postprocesor: łuk ze zmianą Z = helisa `CP IPA… IZ… DR±` (kąt z punktów; pełny obrót,
  gdy koniec = początek). **IZ liczone z zaokrąglonych wysokości** (jak programy warsztatu:
  `IZ-0.131`/`-0.132`), więc przy skoku G1/4 (P/2 = 0.6685) błąd się nie sumuje. Tytuł
  `*- Thread Milling`. Jedna świadoma różnica z programem warsztatu: `R0` na wjeździe posuwem przy
  każdym otworze (tam jest tylko przy pierwszym).
- Engine: podklasa `ObjectThreadMilling` FreeCADa (`engine/thread_milling.py`), ścieżka
  z `freecad_cam.thread_moves` (G2 z Z, I/J); właściwości FreeCADa (MajorDiameter,
  MinorDiameter = D − 1.0825 P, Pitch, Passes, ThreadName, Conventional, RightHand) z
  wartości usera, więc tryb eksperta je pokazuje. Otwory jak w wierceniu: okręgi szkicu
  (`add_thread_milling`) albo otwory modelu (`add_model_thread_milling`), te same obiekty
  pomocnicze (`_circles_helper`, `_model_holes_helper`). Odrzuca: narzędzie, które nie
  jest frezem do gwintów, frez ≥ Ø gwintu, frez, który nie wchodzi w otwór, gwint głębszy
  niż nieprzelotowy otwór modelu.
- **Okno** (`ui/thread_dialog.py`, CAM > Thread milling, w Details szkicu „Thread
  milling...”): otwory jak przy wierceniu (`handlers._picked_holes`, wspólne z Drilling),
  narzędzie: frez do gwintów, który wchodzi w otwory i którego skok daje z nich gwint
  normowy (`suggested_mill`, materiał jak przy wiertłach), inaczej ostatnio użyty
  (`LastThreadTool`), inaczej pierwszy frez do gwintów mocowania. Pola `ThreadFields`:
  Major diameter (podpowiedź z otworu i skoku, aż user wpisze swoją; obok nazwa „M5”),
  Depth, Passes; pod spodem Feeds i Helix („10 turns of P0.8, 2 passes”). Ostrzeżenie i
  odmowa OK: nie frez do gwintów, frez nie wchodzi, gwint głębszy niż otwór. Okno pamięta
  głębokość i przejścia (`LastThreadMilling`). **Details** (`details.ThreadMillingView`):
  te same pola na żywo z undo, Change tool..., Remove operation; menu operacji Edit...
- Pułapka (złapana testem GUI): sygnał pola średnicy szedł do `_update` przed flagą
  „wpisane ręcznie”, więc wpisana średnica wracała do podpowiedzi; stąd osobny sygnał
  `major_edited` emitowany przed `typed`.

## Adaptive clearing (Adaptive)

Pierwszy plik testowy: płytka testowa E (w Setup 1 wierzch płyty na Z-1.5, żeberko 20×6 do Z0, półfabrykat do Z+1). Decyzje usera (2026-10-20):

- **Obszar**: bez zaznaczenia zgrubnie **cały model mocowania** od góry półfabrykatu do
  Z-Depth (to, co narzędzie sięga poza modelem, także naddatek po obrysie); kliknięte
  płaskie dna (Shift+klik) zawężają obszar do nich.
- **Poziom Z na każdym płaskim dnie** modelu skierowanym do narzędzia (FreeCAD tnie tylko
  na swoich krokach Z, więc dno między krokami zostawało z naddatkiem do kroku).
- Helisa w programie **łukami** `CC` + `CP IPA… IZ… DR-` (półobroty, jak gwinty).
- Przejazdy po wyczyszczonym dnie **FMAX 0,5 mm nad poziomem** (`LIFT_MM`), nad nieściętym
  materiałem w górę na wysokość bezpieczną.
- **Start Z** (2026-10-26): górna granica zakresu, w którym liczone są poziomy, sam nie jest
  poziomem (pierwszy poziom = Start Z − Z step, ostatni = Z-Depth). Domyślnie zaznaczone „Top of
  the stock” (None = góra półfabrykatu, jak wcześniej; nie zapamiętywany, jak w Facing). Dno
  modelu na Start Z albo niżej dostaje poziom, wyżej — zostaje nietknięte. Start Z = Z-Depth =
  wierzch detalu: jeden poziom, czyści tylko półfabrykat nad nim; Start Z −0,1 i Z-Depth −3,5:
  wierzch zostaje, czyści to, co niżej. Z-Depth nad Start Z = błąd. Na razie tylko bez
  zaznaczania (user: zaznaczanie później, „najpierw prosto”). Sprawdzenie długości ostrza
  liczy dalej od góry półfabrykatu (to, co nad Start Z, i tak zbierze pierwszy poziom).
- **Poziom samego dna czyści tylko wokół tego dna** (2026-10-27, zgłoszenie usera na płycie
  płyta testowa A: Start Z −0,1, Z step 8, pogłębienia Ø8 na −5,5, półki na −3,5, kieszenie na −10):
  „wchodzi do otworu 6 mm deep, nie powinien jeździć dookoła produktu […], reszta będzie
  wyczyszczona po zjechaniu na 8 mm zgodnie z Z-step”. Cały obszar tylko na **pełnych
  poziomach** (kroki Z od Start Z i Z-Depth + naddatek Z); bez Z step wszystko poza dnami
  schodzi na Z-Depth na raz, a długość ostrza sprawdzana jest między pełnymi poziomami. Na
  płycie usera droga posuwem 39 448 → 21 441 mm, ruchów 59 458 → 36 139.

Jak to działa:

- **Model** (`model/operations.Adaptive`): Z-Depth w układzie mocowania (Z programu, nie od
  szkicu), Start Z (None = góra półfabrykatu), Z step (None = bez kroków), step over w % średnicy (FreeCAD: 20), naddatki XY i Z,
  kąt helisy (FreeCAD: 5°), podniesienie 0,5 mm, przejście wykańczające wzdłuż ścian
  (FreeCAD: FinishingProfile). `levels(góra półfabrykatu, dna)`: pełne kroki od Start Z
  (`top_mm`), poziom „dno + naddatek Z” na każdym dnie od Start Z w dół, nie niżej niż Z-Depth i najniższy
  poziom **Z-Depth + naddatek Z** (`bottom_mm`); nic na górze półfabrykatu i wyżej. Naddatek Z
  zostaje więc na dnach modelu i nad Z-Depth także obok detalu (user, 2026-10-20: wcześniej
  na samym Z-Depth narzędzie cięło do końca i przy Z-Depth = dno płyty z naddatkiem 0,1 objeżdżało
  krawędź detalu 0,1 mm poniżej naddatku).
- **Ruchy** (`model/clearing.py`, czysty Python): obszar liczony raz na kilka poziomów to
  `Piece` (poziomy, góra materiału, środek helisy albo None, start, ścieżki CUT / LINK / UP
  z FreeCADa). Kolejność: poziom po poziomie od góry, na każdym obszary w kolejności. Dojazd:
  nad pierwszy start na Z+20 (wrzeciono), szybko 2 mm nad półfabrykat, posuwem Z w dół. Każdy
  obszar: szybko na 2 mm nad miejsce, gdzie ten obszar był już cięty (pierwszy raz: poziom
  wyżej, tam materiał już zszedł; od 2026-10-27 pełny poziom wyżej albo góra półfabrykatu, bo
  poziom samego dna nie czyści całości), posuwem Z do niego, potem helisa półobrotami w prawo
  (posuw Z) i jeszcze cały obrót na poziomie (posuw XY, czyści środek), albo prosto w dół obok
  półfabrykatu, gdy obszar jest otwarty. Po obszarze w górę na wysokość bezpieczną.
- **Tłumacz**: operacja Adaptive FreeCADa z proxy `engine/adaptive.Adaptive` (podklasa
  `PathAdaptive`; tryb eksperta pokazuje wartości FreeCADa: ModelAwareExperiment, UseHelixArcs,
  StepOver, StockToLeave, ZStockToLeave, HelixAngle, LiftDistance…). Ścieżka to środek
  narzędzia; program czyta ją jak kontur bez kompensacji (`nc_moves`), tytuł
  `*- Adaptive Clearing` (mój wybór, po angielsku jak wiercenie). Kliknięte dna to `Base` na
  klonie modelu w Jobie (`picked_floors`: płaska ściana zwrócona do narzędzia, inaczej
  czytelny błąd). Zmiana zera, półfabrykatu albo narzędzia przelicza (`_sync_adaptive`).
  Sprawdzenia przed zmianą (`_check_adaptive`): frez (Endmill/Bullnose/Ballend), Z-Depth poniżej
  góry półfabrykatu, najgłębsze cięcie (między pełnymi poziomami, `full_levels`) nie głębsze
  niż długość ostrza narzędzia (komunikat: „Enter a Z step”), najwyżej 5000 poziomów.
- **Obszary**: cały model = pomocnik FreeCADa `_workingEdgeHelperRoughing` (obrys półfabrykatu
  minus obrys modelu nad poziomem; kieszenie zamknięte modelem osobno, z helisą). Kliknięte dna
  = `_picked_regions`: obrys den widziany od narzędzia (bez ich otworów, bo te idą w dół)
  powiększony o **promień narzędzia** (środek dochodzi do krawędzi dna, jak „tool outside
  boundary” w Fusion), w półfabrykacie, minus model nad poziomem. Obszar sięgający krawędzi
  półfabrykatu jest czyszczony jak cały model („outside”: reszta półfabrykatu jest strefą
  zakazaną, narzędzie wchodzi z zewnątrz i może tam jeździć), zamknięty helisą („inside”).
  Tak tylko na pełnych poziomach (`Adaptive.full_levels`). **Poziom samego dna**
  (`_floor_regions`): obrys den leżących na tym poziomie (bez ich otworów) powiększony o
  `FLOOR_REACH` = 1,5 średnicy narzędzia + Finish XY (frez sięga całego dna z miejsca obok niego,
  z miejscem na helisę ½ średnicy), z klikniętymi dnami także w ich obszarze, minus model nad
  poziomem, **nie przycinany do półfabrykatu** i zawsze „inside”: gdzie wystaje poza półfabrykat,
  libarea sama wchodzi z zewnątrz (`FindEntryPointOutside`), a przejście wykańczające idzie tylko
  po brzegu tego obszaru. Gdzie wystaje, `_out_of_stock` poszerza go poza półfabrykatem tak, żeby
  sięgał średnicę narzędzia + Finish XY + 1 mm od półfabrykatu (niżej, pułapki). Każdy obszar
  czyści Adaptive2d z libarea.
- **Pułapki FreeCADa / libarea (sprawdzone na pliku usera i w testach):**
  - **Rzut modelu nad poziomem** (`_getSolidProjection` FreeCADa) potrafi się wywrócić: na płycie
    płycie testowej A (poziome otwory w boku Ø4.2 z ostrzem wiertła, góra otworu na Z-5.4)
    przekrój między Z-5.5 a Z-5.4 zostawia okruchy stożka (0,04 mm²), fuzja z nimi daje
    11 mm² zamiast 24 775 mm² i poziom -5.4 frezował CAŁĄ płaszczyznę przez model (2026-10-26).
    `engine/adaptive.solid_projection`: rzut ściana po ścianie, ściana widziana mniejsza niż
    `SLIVER_MM2` = 1 mm² liczy się jako jej prostokąt obrysu (trochę więcej modelu, nigdy mniej),
    wynik mniejszy niż największa ściana albo niepoprawny = ProjectError zamiast ścieżki.
    Pomocnik FreeCADa `_workingEdgeHelperRoughing` dostaje ją na czas wywołania
    (`_safe_projections`). Facing (`engine/facing.py`) dalej używa rzutu FreeCADa.
  - FreeCAD przecina model **dokładnie** na wysokości poziomu, więc dno leżące na poziomie
    liczy się jako materiał nad narzędziem i nie jest cięte (na płytce usera wierzch płyty
    zostawał na Z-1.0 zamiast Z-1.5). Przecinamy `EPSILON_MM` = 0,001 mm nad poziomem.
  - FreeCAD przy klikniętych ścianach trzyma **całe narzędzie** w ich obrysie: płyta usera
    (Ø6, 5,75 mm między otworem a krawędzią) była czyszczona tylko między otworami.
  - Obszar „inside” wystający poza półfabrykat o mniej więcej średnicę narzędzia: Adaptive2d
    wchodzi z zewnątrz i prawie nic nie tnie (stąd podział na otwarte/zamknięte).
  - Obszar „inside” wystający poza półfabrykat **mniej niż o średnicę narzędzia** (2026-10-30,
    plik usera: płyta 70×40, półfabrykat 2,1 mm szerszy z każdej strony i 5,1 dłuższy, Ø6, step
    over 10%; obszar wokół wierzchu płyty wystawał 4,1 mm na długich bokach): Adaptive2d wchodzi
    z zewnątrz po obrysie półfabrykatu odsuniętym o 0,9 promienia, a środek narzędzia nie mógł
    tam stanąć, więc wszedł tylko na krótkich końcach, zebrał pasek i uznał resztę za
    wyczyszczoną („All cleared”: zostawia tylko dziury dalej niż średnica od brzegu obszaru).
    Przejście wykańczające zdjęło potem 2 mm z długich boków z materiałem po lewej stronie
    narzędzia (przeciwbieżnie, 85% zebranego materiału), libarea ostrzegło „some cuts may be
    above optimal step-over”, a wierzch został z 2,5 mm. Tak samo w mocowaniu 1 z pudełkiem i w
    mocowaniu 2 ze stockiem z mocowania 1. `_out_of_stock` dokłada poza półfabrykatem pas do
    średnicy + Finish XY + 1 mm (tylko przy miejscach, gdzie obszar już wystaje, minus model
    nad poziomem); wynik musi być jedną ścianą (`DraftGeomUtils.concatenate`): po fuzji FreeCAD
    zostawiał obrys półfabrykatu jako krawędź między dwiema ścianami i libarea nie cięło nic.
    Test `test_adaptive_floor_level_near_the_stock_edge` liczy też stronę freza (współbieżnie
    = materiał po prawej przy M3).
  - Fuzja OCCT często NIE daje jednej ściany (2026-11-02, płyta testowa D:
    300×92,5, dwie kieszenie 3,5 mm otwarte do końca płyty, stock 5 mm dłuższy, Ø6): łuki wokół
    dwóch półek schodziły się 0,04 mm W półfabrykacie, część obszaru poza nim rozpadła się na
    trzy, fuzja zostawiła dwie stykające się ściany i `_out_of_stock` po cichu zwracał obszar bez
    zmian (tak samo w testach z nokiem/kieszenią i na płytach testowych A, B i detalu C —
    tam libarea akurat dawało radę). Na płycie testowej D libarea nie zebrało nic w kieszeniach,
    dało samo przejście wykańczające (pełna głębokość w pełnym materiale, „some cuts may be
    above optimal step-over”), a nasz kod jechał do jego początku G1 prosto: 70 mm przez żebro
    między kieszeniami, 3,4 mm w wierzch detalu. Teraz `_joining`: najpierw fuzja OCCT, a gdy
    ściany się stykają, unia libarea (`Path.Area`, Clipper, Accuracy 0,001 → 1,6 µm od ścian);
    dziurki < `SLIVER_MM2` bez modelu w środku (tam, gdzie łuk wchodził w półfabrykat: 0,06×0,04
    mm) usuwane, bo frez trzymałby od nich promień. Pas dokładany do obszaru jest nadal tylko
    POZA półfabrykatem: wariant z pasem także w półfabrykacie (jedna ściana od razu) sprawiał,
    że libarea znów nie zbierało nic (55% pokrycia = samo wykańczanie) — libarea jest kapryśne.
    Skutek uboczny (zamierzony od 1e5b1f3, wcześniej niedziałający): na poziomie dna przy
    krawędzi półfabrykatu frez rusza się też w powietrzu obok niego i zbiera naddatek przy
    detalu w zasięgu dna (testy `test_adaptive_around_the_model`, `…_floor_between_steps`
    poprawione); na plikach usera droga posuwu +0–2%.
  - Siatka bezpieczeństwa `_joined` (w `_clear`): cięcie libarea zaczynające się dalej niż
    `JUMP_MM` = 1 mm (albo 2× tolerancja) od miejsca, gdzie stoi frez, dostaje przed sobą
    przejazd UP (bezpieczna wysokość, przelot, zjazd z posuwem Z) i ostrzeżenie w raporcie.
    Zwykłe przerwy libarea: 0,03 mm między cięciami, 0,1 mm po przejeździe LINK; FreeCAD sam jedzie
    do każdego cięcia G1 prosto. Na plikach usera po poprawce nie zadziałała ani razu.
    Testy: `test_adaptive_floor_level_arcs_meeting_in_the_stock` (bez poprawki pada: kieszenie
    niezebrane), `test_adaptive_cut_apart_from_the_tool`, `test_adaptive_sliver_holes`.
  - Helisa domyślnie ma średnicę narzędzia; gdy się nie mieści (kieszeń 14×10, Ø6),
    Adaptive2d **po cichu pomija obszar**. Ponawiamy z helisą ½, ¼ i ⅛ średnicy (`HELICES`,
    `_clear_area`). Pogłębienie Ø8, frez Ø6, Finish XY 0.2: helisa Ø1.5 ma 0.05 mm zapasu i wchodziła
    albo nie zależnie od tego, gdzie wypadły punkty wielokąta libarea (płyta usera obrócona o 90°:
    wszystkie pięć albo żadne); ⅛ ma 0.43 mm. Naddatek XY libarea odejmuje od obszaru przed
    sprawdzeniem helisy, więc żadna helisa go nie zjada. Test `test_adaptive_tight_counterbore`.
  - FreeCAD robi przejście wykańczające także po obrysie „overshoot” poza półfabrykatem (tnie
    powietrze wokół półfabrykatu na każdym poziomie); zostawione jak w FreeCADzie. Obszar
    poziomu dna jako „outside” (strefa zakazana = półfabrykat minus obszar) dawał to samo dla
    półek usera: 950 mm w powietrzu dookoła półfabrykatu na Z-3.4 — stąd „inside” bez przycięcia.
    Przycięty do półfabrykatu „inside” wchodził helisą i zostawiał naroża półki przy krawędzi.
  - Wejście z zewnątrz: libarea zaczyna obszar „outside” z frezem zachodzącym na półfabrykat
    o step over (0,5 mm przy Ø10 i 10 %), obszar poziomu dna nawet 1,2 mm (płyta usera) do
    2,7 mm (test) = zjazd bokiem freza po krawędzi półfabrykatu na całą głębokość (user, detal
    na maszynie: w nierdzewce niszczy frez). `_in_from_outside`: frez zawsze schodzi
    `OUTSIDE_GAP_MM` = 1 mm od półfabrykatu prosto na zewnątrz od startu i dojeżdża do niego
    na poziomie.
  - Verify pokazywał na płycie usera kolizje FMAX w pogłębieniach Ø8 (Z-4.9, przejazd nad
    dnem zaraz po helisie R0,74, 0,02–0,3 mm³): artefakt stocklab, nie programu — łuki szły
    cięciwami do 0,25 komórki (0,3 mm przy Medium), helisa była w symulacji prawie kwadratem.
    Poprawione w Labie (6a1a576, cięciwy 0,02 komórki, kopia odświeżona 2026-10-27): 0 kolizji
    przy Medium i Fine, gwinty bez otworu nadal wykrywane. Helisa nadal idzie 0,01 mm do środka
    promienia libarea (jak w FreeCADzie).
  - Ścieżka libarea zależy od ostatnich cyfr kształtu: po zapisie i otwarciu pliku liczba
    ruchów może się nieco różnić. Różni się też między dwoma przeliczeniami tego samego pliku
    (test_adaptive_something_wrong: 520, 569, 582, 550 ruchów, droga posuwu 605–614 mm).
- **Okno** (`ui/adaptive_dialog.py`, CAM > Adaptive, `handlers.adaptive`): nic nie zaznaczone
  = cały model; ściany kliknięte w modelu (Shift+klik dodaje) = te dna (krawędzie: komunikat,
  ściany dwóch modeli: komunikat). Mocowanie: aktywne, gdy dna patrzą na jego narzędzie,
  inaczej pierwsze, na które patrzą (bez mocowania powstaje pierwsze). Wiersze: Area („Around
  the whole model (Body)” / „1 floor of Body: Z +0.00”), narzędzie (`ToolChooser`; ostatnio
  użyte `LastAdaptiveTool`, inaczej pierwszy frez mocowania), posuwy, pola `AdaptiveFields`:
  Z-Depth (podpowiedź `suggested_adaptive_depth`: najniższe kliknięte dno, inaczej najniższe
  dno modelu), Z step (0 = bez kroków), Step over w % z przeliczeniem na mm obok, Finish XY,
  Finish Z, pod zwijanym Advanced kąt helisy, podniesienie i przejście wykańczające. Pod spodem
  **Z levels** liczone na żywo („Z +0.00, -3.00, … (5 levels)”, pokazuje też poziomy den).
  Ostrzeżenie i odmowa OK: nie frez, Z-Depth nad półfabrykatem, poziom głębszy niż długość
  ostrza. Okno pamięta wartości poza Z-Depth (`LastAdaptive`).
- **Details** (`details.AdaptiveView`): te same pola na żywo (po pauzie, jeden krok undo),
  Area, Z levels, Path („995 moves, down to Z -12.00 mm”), Change tool..., Remove operation;
  menu operacji Edit... otwiera okno z jej wartościami i narzędziem.

## Facing (planowanie płaszczyzny)

Osobne moduły: `model/facing.py` (wartości, poziomy, ułożenie przejść i ruchy, czysty
Python), `engine/facing.py` (obszar z OCCT, proxy operacji, dodawanie i zmiana),
`ui/facing.py` (CAM > Facing, okno, Details, Edit...), testy `tests/test_facing.py` i
`tests_gui/test_facing.py`. We wspólnym kodzie są tylko cienkie wpisy (`freecad_cam`:
przeliczanie, zmiana narzędzia, Edit, program; `handlers`, `project_panel`, `actions`,
`operations.from_json`, `nc.FACING`, tytuł `*- Facing`). „Facing” zamiast „Plane milling”
(decyzja usera: to to samo, krótsza nazwa).

**Na razie tylko góra** (decyzja usera, 2026-10-21, po pierwszej wersji): klik ściany na samej
górze modelu i frez czołowy równa całą górę według stocka. Ściana, nad którą jest cokolwiek z
modelu mocowania (`engine/facing.material_top`), daje komunikat „Facing is for the top of the
model … Click a face at the very top.” (`_check_top` w `picked_face` i `check`). Pole
Offset from walls zniknęło z okna i Details (bez ścian nic nie robi; w modelu zostaje, 0).
Logika ścian, stopni i den poniżej (obszar, przejście wzdłuż ścian, zjazdy w materiał) zostaje
w silniku na później i jest testowana przez `plan_for` (`test_area_beside_walls`).

Pierwotny projekt (decyzje usera 2026-10-21, na później poza górą):

- Klik płaskiej ściany (Shift+klik dodaje następną na tej samej wysokości). Gdy nad nią nic
  nie ma (albo sąsiedzi są na tej samej wysokości), frez tnie po całym stocku. Gdy
  kliknięty jest stopień, czyści płaszczyznę tylko do ścian idących w górę. Ogólnie: każda
  krawędź ściany jest **zamknięta** (ściana w górę: frez staje obok niej) albo **otwarta**
  (nic nad nią, ten sam poziom, stopień w dół: frez wyjeżdża za stock).
- Z step ze **Start Z** (domyślnie góra stocka, `start_z_mm = None` idzie za stockiem) i krokiem
  w osi Z: pełne kroki, reszta na płaszczyźnie (jak kontur i TNC).
- Ścieżka do wyboru: **zygzak z zaokrąglonymi nawrotami** albo **jednostronnie**; wybór
  kierunku pierwszego przejścia X- → X+, X+ → X-, Y- → Y+, Y+ → Y- (to od razu mówi, czy
  przejścia idą wzdłuż X czy Y).
- Frezy w warsztacie są mierzone do najdalszej części, więc odsunięcie od ścian liczy się od
  średnicy z tabeli (`Diameter`). Pole **Offset from walls**: krawędź freza tyle od ścian
  (ujemne: w ścianę, ale środek freza poza nią).

Jak to działa:

- **Obszar** (`engine/facing.Area`, w XY mocowania): strefa zakazana = model nad płaszczyzną
  (`_getSolidProjection` FreeCADa 0,001 mm nad nią) powiększony o R + offset; obszar przejść =
  stock powiększony o R + **overrun** (Advanced, domyślnie 2 mm: krawędź freza wychodzi tyle
  za stock) minus strefa zakazana, tylko kawałki pod klikniętą ścianą. Liczone geometrycznie,
  nie z sąsiadów ściany, więc wyższy materiał, który ściany nie dotyka (np. czop za rowkiem),
  też ogranicza. Nawroty mogą wyjść o średnicę dalej niż przejścia (półkola obok stocka).
- **Przejścia** (`model/facing.rows_at`, `plan`): linie w poprzek materiału (obszar ± R w
  stocku) od strony startu (user 2026-10-22: frez ma zaczynać od skraju, nie „prawie
  środkiem”, jak przy Ø50 z krawędzią freza na krawędzi materiału): każde przejście bierze
  **równo** najwyżej step over (domyślnie 70 % Ø) świeżego materiału, pierwsze wchodzi zza
  skraju (frez wystaje poza stock), ostatnie wyjeżdża krawędzią freza o **overrun** za drugi
  skraj (user 2026-10-22; gdy ten skraj to stock, nie ściana). Każda linia przecięta z obszarem daje odcinki. Zygzak: następne
  przejście startuje po tej samej stronie, łącznik to półkole (za dalszym z dwóch końców), a
  gdy wchodzi w ścianę, prosta wzdłuż niej; gdy nic się nie mieści (np. wyspa), nowy przebieg.
  Przy wyspie zygzak idzie dalej odcinkiem po tej stronie, gdzie jest frez. Nowy przebieg
  zaczyna tak, jak wybrał user, albo odwrotnie, gdy tylko drugi koniec jest poza stockiem.
  Jednostronnie: każde przejście osobno, powrót 2 mm nad materiałem.
- **Strona startu** (user 2026-10-22, pole **Start from**): w poprzek przejść, Y− / Y+ dla
  przejść wzdłuż X, X− / X+ dla przejść wzdłuż Y (`Facing.start_side`). Domyślnie (None) ta,
  od której pierwsze przejście jest współbieżne: wrzeciono M3, więc materiał po lewej, czyli
  X+ przesuwa się w stronę +Y (`Facing.axes`). Współbieżne/przeciwbieżne user ocenia sam, okno
  tego nie opisuje. Przeszkody na drodze (ściany, wyspy) przy innej stronie: na razie bez
  dopracowania (user).
- **Przejście wzdłuż ścian** (mój wybór, zawsze): przejścia leżą równo w poprzek materiału,
  więc przy ścianie równoległej do nich zostawałby pasek. Na każdym poziomie po przejściach
  frez jedzie po krawędziach obszaru, które nie są otwartymi bokami (`Area.walls`: łańcuchy
  prostych i łuków), współbieżnie (ściana po lewej). Łańcuchy otwarte zaczynają i kończą się
  za stockiem; pętla wokół wyspy zjeżdża tam, gdzie przejścia już cięły.
- **Wejścia**: frez czołowy nie wchodzi w materiał z góry. `Plan.closed_entries` liczy zjazdy w
  materiał (np. dno kieszeni bez otwartej krawędzi), okno pokazuje pomarańczowe ostrzeżenie,
  ale pozwala (user zdecyduje, czy narzędzie to zniesie).
- **Ruchy** (`model/facing.moves`): nad pierwszy start na Z+20, szybko 2 mm nad materiał (Start
  Z, potem poziom wyżej), posuwem Z na poziom, przejścia posuwem XY; po przebiegu w górę 2 mm
  nad poziom wyżej i do następnego, gdy droga leży w obszarze, inaczej przez wysokość
  bezpieczną. Na końcu w górę; program kończy jak inne (`Z+40`).
- **Tłumacz**: operacja Mill Facing FreeCADa (`ObjectFace`) z proxy `engine/facing.Facing`, `Base`
  = kliknięta ściana klonu modelu (idzie za zerem), tryb eksperta pokazuje ClearingPattern
  (ZigZag/Line), ZigZagAngle, StepOver, BoundaryShape = Stock. Ścieżka to środek narzędzia,
  program czyta ją jak Adaptive. Sprawdzenia (`check`, `plan_for`): frez płaski (Endmill /
  Bullnose), Start Z nad płaszczyzną, poziom nie głębszy niż długość ostrza, frez mieści się na
  płaszczyźnie obok ścian, ściany na jednej wysokości.
- **Pułapka FreeCADa**: nowa operacja bierze narzędzie poprzedniej operacji mocowania. Gdy jej
  nie ma, a narzędzi jest kilka, FreeCADCmd wysypuje się (`UnboundLocalError` w
  `findToolController`; sprawdzone też dla Adaptive: pierwsza operacja w mocowaniu z dwoma
  frezami), a w GUI FreeCAD otwiera swoje okno wyboru narzędzia „Tool Controller Selection”
  (sprawdzone 2026-10-23: T57 w mocowaniu + nowy T21 do pierwszego konturu). Każde proxy
  (Facing, Slot, Contour, Drilling, ThreadMilling, Adaptive) na czas tworzenia dostaje wybrane
  narzędzie (`tc`) i mówi FreeCADowi, że obsługuje tylko je (`isToolSupported`); każde ma ten
  kod u siebie (zasada izolacji). Testy `test_first_*_among_tools`.
- **Okno** (`ui/facing.FacingDialog`): Face („Face6 of Body: Z +0.00”), narzędzie (ostatnio
  użyte `LastFacingTool`, inaczej pierwszy frez płaski mocowania), Start Z z „Top of the stock”,
  Z step, Step over (% i mm), Pattern, First pass, Start from, Advanced: Overrun; pod spodem
  Z levels, Passes („5 passes, 1 along the walls, on each level”) i ostrzeżenie o zjazdach. Okno
  pamięta wartości poza Start Z (`LastFacing`). **Details** (`FacingView`): te same pola na żywo z
  undo, Change tool..., Remove operation; menu operacji Edit....
- Do zrobienia / do decyzji: kilka wysokości w jednej operacji (teraz komunikat), naddatek w Z,
  wejście łukiem przy zamkniętym dnie, obrazki pól.

## Slot milling (slobgat)

Osobne moduły: `model/slot.py` (wartości, poziomy, rampa, przejścia i ruchy, czysty Python),
`engine/slot.py` (rozpoznanie slobgatu w modelu, proxy operacji, dodawanie i zmiana),
`ui/slot.py` (CAM > Slot, okno, Details, Edit...), testy `tests/test_slot.py` i
`tests_gui/test_slot.py`. We wspólnym kodzie tylko cienkie wpisy (`freecad_cam`: przeliczanie,
zmiana narzędzia, Edit, program; `handlers`, `project_panel`, `actions` (przycisk „Slot”, wcześniej
placeholder), `activate_geometry` (Base, także krawędzie), `operations.from_json`,
`nc.SLOT_MILLING`, tytuł `*- Slot Milling`).

Decyzje usera (2026-10-22): slobgat prosty (dwa półokręgi + dwie równoległe ściany, dowolny kąt
w XY), szerokość ≥ Ø freza; najpierw klikany w modelu 3D, potem ze szkicu; później slobgat po
łuku (jak cykl 254). Program na razie **jawne ruchy L / CC / C**; styl z cyklami (253/254) będzie
opcją postprocesora przy eksporcie (jak dla innych funkcji; tylko wiercenie ma cykl w obu
stylach). Wejście w materiał **rampą wahadłową** wzdłuż osi slobgatu. Ściany wykańczane **z
kompensacją RL/RR** (operator koryguje wymiar przez DR).

- **Na każdym poziomie Z** (od góry slobgatu): rampa tam i z powrotem między środkami końców
  (`model/slot.ramp`, równe zjazdy, nie stromiej niż kąt rampy, posuw Z), jeszcze raz całą osią na
  poziomie (posuw XY), potem przejścia zgrubne środkiem freza (R0) wokół osi (`ring`), równo co
  najwyżej step over, aż do naddatku Finish XY od ścian; powrót na oś. Przy RL wszystko CCW
  (współbieżnie przy M3), przy RR CW.
- **Rampa po konturze** (user 2026-10-22, Advanced > Ramp „Along the contour”, domyślnie dalej
  wahadłowa): zamiast tam i z powrotem frez schodzi dookoła osi po obrysie slobgatu
  (`contour_ramp` na `ring`), odsunięty o `ramp_offset` = min(R, (W−D)/2 − Finish XY), więc w
  środku nie zostaje rdzeń i nie wchodzi w naddatek; całe okrążenia równo, proste z Z i półokręgi
  jako helisy (post: `CP IPA±180 IZ… DR±`), posuw Z, potem jedno okrążenie płasko na poziomie
  (posuw XY). Przejścia zgrubne wewnątrz tego okrążenia odpadają (`passes`), przejazdu osią i
  powrotu na oś nie ma. Mniej niż 0,1 mm miejsca (`MIN_RAMP_OFFSET_MM`, mój wybór) albo slobgat
  szeroki jak frez → rampa wahadłowa (opis przejść to mówi).
- **Poziomy** jak kontur: pełne kroki Z od góry, reszta na dnie; z Finish Z zgrubne kończą tyle nad
  dnem, a ostatni poziom czyści dno (`levels`).
- **Wykańczanie ścian** po wszystkich poziomach zgrubnych, **tymi samymi krokami Z** (jak ściana
  konturu; ostatni = dno, `wall_levels`): w górę na 2 mm nad slobgat, nad środek łuku dojazdu,
  w dół w wyczyszczonym slobgacie, prosta z RL/RR do łuku, łuk 45° na środek ściany
  (`model.leads`, jak kontur), raz dookoła, łuk z powrotem i prosta do środka łuku z R0. Domyślny
  promień łuku = R + max(0,5 mm, Finish XY) (frez schodzi obok naddatku, nie w niego), najwyżej
  połowa slobgatu; wpisany musi być > R i ≤ połowa szerokości.
- Bez naddatku XY ostatnie przejście zgrubne pokrywa się z wykańczającym, więc go nie ma.
- **Slobgat szeroki jak frez** (różnica < 0,02 mm, `SAME_WIDTH_MM`, mój wybór): tylko rampa i
  przejazd osią na każdym poziomie, bez wykańczania (TNC nie zrobi kompensacji w łuku o promieniu
  narzędzia); naddatek XY wtedy = błąd.
- **Rozpoznanie w modelu** (`engine/slot.slot_in_model`, na klonie modelu w Jobie, więc w układzie
  mocowania): z klikniętej ściany bocznej, półwalca końca, dna albo krawędzi szukane są dwa pionowe
  walce o tym samym promieniu (bezpośrednio, przez sąsiednie ściany, przez łuki dna); kształt
  potwierdzają próbki materiału (w środku i nad górą pusto, za ścianami i za końcami materiał).
  Przelotowy, gdy tuż pod dnem ścian nie ma materiału. Komunikaty: okrągły otwór („Use Drilling or
  Thread milling”), jeden koniec („a slot running out of the part?”), końce o różnej głębokości,
  zamknięty od góry. Start = koniec o mniejszym X (potem Y). Kilka slobgatów (Shift+klik) w
  kolejności kliknięć, każdy raz.
- **Głębokość**: domyślnie z modelu (dno, przelotowy: `through_mm` = 1 mm pod spód, jak
  wiercenie), albo wpisana od góry każdego slobgatu; głębiej niż dno ślepego = błąd.
- **Tłumacz**: operacja Slot FreeCADa (`ObjectSlot`) z proxy `engine/slot.SlotMilling`, Base =
  kliknięte elementy klonu modelu. Ścieżka FreeCADa = środek narzędzia (`moves(..., program=False)`:
  pierścień wykańczający R od ściany, łuk dojazdu mniejszy o R wokół tego samego środka); program
  bierze ruchy z kompensacją wprost z modelu (`program_moves`, jak gwinty). Widok 3D rysuje
  program (`engine/slot.path_drawing`, podpięte w `cam.path_drawing`, kolory jak kontur z RL/RR):
  rampy i zgrubne środkiem freza (czytelne), wykańczanie po ścianach, gdzie tnie krawędź z
  kompensacją; linie FreeCADa (środek) ukryte. Ta sama obejście
  wyboru narzędzia co Facing (`isToolSupported`). Sprawdzenia (`slot_cuts`): frez
  (Endmill/Bullnose/Ballend), frez nie szerszy od slobgatu, naddatek XY mieści się, krok nie
  głębszy niż długość ostrza.
- **Okno** (`ui/slot.SlotDialog`): Slots („Slot 30 × 10, 6 deep in Body”), narzędzie (ostatnio
  użyte `LastSlotTool`, inaczej pierwszy frez mocowania), Depth z „From the model”, Out under
  through slots, Z step, Step over (% i mm), Finish XY, Finish Z, Finishing (RL: climb with M3 / RR:
  conventional with M3), pod Advanced kąt rampy (domyślnie 5°, mój wybór) i Approach radius z
  „Auto”; pod spodem Z levels pierwszego slobgatu i Passes. Okno pamięta wartości poza głębokością
  (`LastSlotMilling`). **Details** (`SlotView`): te same pola na żywo z undo, Change tool..., Remove
  operation; menu operacji Edit... i Activate geometry.
- Moje wybory do potwierdzenia: kąt rampy 5°, step over 50 %, wykańczanie po zgrubnym (nie
  poziom po poziomie), wykańczanie tymi samymi krokami Z, start na końcu o mniejszym X, tytuł
  programu, próg 0,02 mm „szeroki jak frez”, rampa posuwem Z. Później: slobgat ze szkicu, po łuku,
  cykle 253/254 przy eksporcie, Start Z (góra półfabrykatu nad slobgatem: dziś frez schodzi
  posuwem Z od góry slobgatu).

## Frezowanie otworów po helisie (Helix)

Osobne moduły: `model/helix.py` (wartości, przejścia, ruchy; czysty Python), `engine/helix.py`
(proxy operacji, dodawanie i zmiana, program, rysunek), `ui/helix.py` (CAM > Helix, okno, Details,
Edit...), testy `tests/test_helix.py` i `tests_gui/test_helix.py`. We wspólnym kodzie tylko cienkie
wpisy (`freecad_cam`: przeliczanie, zmiana narzędzia, Edit, rysunek, program; `handlers`,
`project_panel`, `actions` (przycisk „Helix”, wcześniej placeholder), przycisk „Helix milling...” w
Details szkicu, `operations.from_json`, `nc.HELIX_MILLING`, tytuł `*- Helix Milling`).

Prośba usera (2026-10-26): wyfrezować otwór spiralą bez wiercenia albo poszerzyć za mały odwiert;
w warsztacie spiralą robi się otwory tolerowane, bo nie zostaje ślad wejścia. Wzór: prawdziwy
program warsztatu (dwa otwory Ø4.5 na 16 mm frezem T2 Ø3; detal z
numerem artykułu, **nie do repo**), odtworzony blok w blok (`tests/test_helix.test_like_the_shop`):

- nad otwór, `Z+20` z `M3 M8`, 2 mm nad górę otworu, posuwem Z na górę (Z0), prosto ze środka z
  `RL` do punktu R freza + 0,1 mm od środka po przeciwnej stronie (`LEAD_START_MM`: środek freza
  0,1 mm obok środka otworu), półokrąg styczny do ściany (`CC` w połowie, `C … DR+`), helisa w dół
  **równymi** półobrotami przeciwnie do wskazówek (`CC` + `CP IPA+180. IZ-0.131 DR+`; IZ z
  zaokrąglonych wysokości, jak gwinty), pełny okrąg na Z-Depth (dwa półokręgi `C`), półokrąg z
  powrotem przez otwór, `L X… R0` do środka; między otworami `Z+10`, po ostatnim `Z+40`. Ta sama
  świadoma różnica co w gwintach: `R0` na wjeździe posuwem przy każdym otworze.
- Skok domyślnie (Auto) = Ø freza × tan 5° do 4 miejsc (Ø3: 0.2625 → 122 półobroty na 16 mm jak
  w programie warsztatu; reguła odczytana z jednej próbki, mój wybór). Półobroty równe, nie głębsze niż P/2
  (`half_turns`); nieparzysta liczba kończy po drugiej stronie, stamtąd okrąg i zejście.
- Decyzje usera: kompensacja od pierwszego przejścia; Finish XY = przejście zgrubne zostawia
  naddatek, ostatnie go zbiera (dwie spirale, 0 = jedna; domyślnie 0,1 mm, mój wybór); XY offset
  ± (większy/mniejszy otwór pod pasowanie); drugi sposób „Helix, then circles”: pierwsze przejście
  helisą, kolejne (poszerzanie i wykańczanie) okręgami na krokach Z od góry (0 = tylko na Z-Depth),
  z tym samym półokręgiem na i ze ściany, zjazd w wyciętym otworze (szybko do 2 mm nad poziom,
  dalej posuwem Z); Z-Depth trzymane (pełny okrąg na dnie); duże otwory i otwory wiercone
  wcześniej (pole Drilled Ø) poszerzane krokami.
- Przejścia (`walls`, promienie tam, gdzie tnie krawędź): zgrubne równo co najwyżej step over od
  promienia otworu wierconego (albo od R freza: frez w środku) do ściany − Finish XY, potem ściana.
  Pierwsze przejście nie zostawia rdzenia (krok ≤ R + R wierconego). Domyślny step over 50 %.
- Sprawdzenia (`check`, `engine.hole_cuts`): frez (Endmill/Bullnose/Ballend), ściana ≥ R freza +
  0,01 mm (TNC nie skompensuje okręgu jak frez), otwór wiercony mniejszy od gotowego, Finish XY
  zostawia miejsce na przejście zgrubne, skok ≤ długość ostrza, okręgi nie głębsze niż ostrze (inaczej
  „enter a Z step”), głębiej niż dno ślepego otworu modelu = błąd; najwyżej `MAX_CUTS` półobrotów.
- Otwory jak w wierceniu i gwintach: okręgi szkicu albo otwory modelu, w kolejności kliknięć, te same
  obiekty pomocnicze (`_circles_helper`, `_model_holes_helper`), więc Activate geometry działa bez
  zmian. Głębokość: otwory modelu domyślnie „From the model” (koniec walca, przelotowy 1 mm pod
  spód), szkic: wpisana od góry otworów.
- **Tłumacz**: operacja Helix FreeCADa (`ObjectHelix`) z proxy `engine/helix.HelixMilling`; ścieżka =
  środek narzędzia (symulacja), program = ruchy z kompensacją wprost z modelu (`program_moves`), widok
  3D rysuje program (ściany, `path_drawing`). Właściwości FreeCADa (StepDown = skok, StepOver,
  StartRadius = R wierconego, OffsetExtra = −offset, CutMode Climb/Conventional) dla trybu eksperta.
- **Okno** (`ui/helix.HelixDialog`): Holes, narzędzie (ostatnio użyte `LastHelixTool`, inaczej pierwszy
  frez mocowania), Depth z „From the model”, Out under through holes, Pitch z „Auto”, Finish XY,
  XY offset, Step over (% i mm), Drilled Ø, Passes (Helices / Helix, then circles), Z step (tylko przy
  okręgach), Compensation (RL: climb with M3 jak programy warsztatu / RR); pod spodem przejścia pierwszego
  otworu („2 helices: Ø4.3, Ø4.5 (finishing); 61 turns of P0.2625 each”). Okno pamięta wartości
  (`LastHelixMilling`) **bez** głębokości modelu, XY offsetu i Drilled Ø (należą do otworów; zapomniany
  offset zrobiłby zły otwór, mój wybór). **Details** (`HelixView`): te same pola na żywo z undo.
- Pułapka: pola długości FreeCADa (`Gui::QuantitySpinBox`) zaokrąglają do miejsc z ustawień jednostek
  (domyślnie 2; profil usera nie zmienia), także rawValue: wpisane 0.2625 dawało 0.26. Skok (4 miejsca),
  Finish XY i XY offset (3 miejsca) są więc zwykłymi `QDoubleSpinBox` z jednostką „mm”.

## Program NC (postprocesor)

- **Heidenhain TNC 620, Klartext `.H`** (`post/heidenhain.py`), na razie dla jednej
  maszyny (Bridgeport V1000). Format jest skopiowany z programów, które warsztat puszcza na tej
  maszynie, i sprawdzony testem złotym: z opisu kwadratu 100×100 postprocesor robi
  **bajt w bajt** ten sam plik co próbka warsztatu (`tests/test_post.py`). Szczegóły:
  niderlandzkie teksty sterowania (`CYCL DEF 247 REF.PUNT VASTL.`), każda linia
  numerowana od 0 (także linia `Q339`), liczby ze znakiem i kropką (`X+50.`,
  `Y-4.667`), struktura `*- Contourbewerking` i `  *- <narzędzie> - TOOL#: … -
  Diameter: Ø…`, `TOOL CALL n Z S… DL0 DR0;nazwa`, `TOOL DEF` następnego narzędzia
  (po ostatnim: pierwszego), posuwy w `FN0: Q30` (Z) i `Q31` (XY), w ruchach `FQ30`
  /`FQ31` (inny posuw jako liczba), `R0` na ruchach szybkich i pierwszym roboczym po
  nich, osie modalne, łuki `CC` + `C … DR±` (pełny okrąg: koniec = początek).
  Kompensacja promienia: `RL`/`RR` na bloku L w XY, który ją włącza (`L X-4.667
  Y+51.933 RL FQ31` albo `L X… Y… RL FMAX`), `R0` na tym, który ją wyłącza; przy
  włączonej kompensacji ruchy nie mają słowa R (`L Z+2. FMAX`). Zmiana na ruchu bez
  XY dopisuje bieżące X Y, zmiana na łuku to błąd. Operacja, która kończy się z
  włączoną kompensacją, wychodzi z nią w górę i wyłącza ją nad produktem
  (`L Z+40. FMAX`, `L X… Y… R0 FMAX`). Drugi test złoty: ten sam kwadrat z RL i
  łukiem 1,1 × R jest bajt w bajt jak próbka warsztatu.
  Koniec narzędzia `L Z100` / `M01` / `L Z100 … M5 M9`, koniec programu park
  `M91 M31`, `M30`. Plik ISO-8859-1 (znak Ø) z CRLF.
- **Mocowania** (decyzja usera): jeden program na cały projekt, mocowanie N na
  presecie N (`CYCL DEF 247 Q339=+N`), jak w ich programach z kilkoma imadłami.
  Przed zmianą presetu narzędzie idzie na `Z100`. `BLK FORM` tylko z pierwszego
  mocowania. Punkt zerowy zawsze z CAM-u: operator ustawia preset tak, żeby się
  zgadzał.
- **Wysokości** (decyzja usera, jak w programach warsztatu, `model/operations.py`): dojazd nad
  pierwszy punkt najpierw w XY, potem `Z+20` z `M3 M8`, potem szybko 2 mm nad górę
  półfabrykatu, wjazd posuwem Z, po operacji `Z+40`. Tłumacz wpisuje je w
  ClearanceHeight/SafeHeight operacji (bez wyrażeń SetupSheet), więc ścieżka w 3D
  pokazuje to samo co program. Wysokości idą za zmianą półfabrykatu i zera.
- **Engine** (`freecad_cam.nc_program`, `nc_moves`): dla wiercenia cykl (patrz Wiercenie),
  dla reszty czyta `op.Path.Commands`
  (G0/G1/G2/G3, I/J względne), posuwy FreeCADa są w mm/s, więc idą przez
  `Units.Velocity` na mm/min. Pomija nieaktywne operacje. Nieznane polecenia
  (np. cykle wiercenia) dają czytelny błąd zamiast złego programu; frezowanie gwintów
  idzie z `thread_moves` (z kompensacją RR), a slobgaty i otwory po helisie z ruchów swoich
  modeli (z RL/RR), nie ze ścieżki.
- Eksport: File > Export NC program… i CAM > Export NC (`handlers.export_nc`),
  nazwa programu (`BEGIN PGM`) z nazwy pliku.
- Później (user): styl z cyklami dla konturu (`LBL` + cykl 25), wybór formatu przy
  eksporcie, inne sterowania. Wiercenie już idzie cyklem 205.

## Pomiar (Measure)

Osobne moduły: `engine/measure.py` (geometria), `ui/measure.py` (zaznaczenie, okna,
obie akcje), testy `tests/test_measure.py` i `tests_gui/test_measure.py`. W
`handlers.py` są tylko `measure_from_zero` i `measure_local`, które delegują dalej. Nic
innego nie używa tych modułów, więc żadna zmiana w pomiarze nie dotknie ścieżek.
Pomiar tylko czyta kształty, zero mocowania (`freecad_cam.zero`), zaznaczenie
(`freecad_cam.model_element`) i otwór tak, jak go widzi wiercenie (`geometry.model_hole`).

- **Measure from 0-Point**: skrajne X, Y, Z (min, max, rozmiar) zaznaczonych ścian i
  krawędzi modelu, linii szkiców albo całych modeli, liczone razem od zera aktywnego
  mocowania. Kształty przenosi `zero⁻¹`, pudełko z `optimalBoundingBox(False, False)`,
  więc walec ma dokładne skrajne punkty, nie pudełko triangulacji.
- **Measure local**: jeden albo dwa elementy, w kolejności kliknięć, w osiach
  mocowania. Wyniki:
  - płaska ściana: wymiary w jej płaszczyźnie wzdłuż osi mocowania („Along X/Y/Z”, a
    gdy w płaszczyźnie leży tylko jedna oś, to „Along X” i „Across”; dla ściany ukośnej
    „Length/Width” wzdłuż najdłuższej prostej krawędzi) i jej poziom („At Z”) albo kąt
    do płaszczyzny XY;
  - otwór (ściana albo okrągła krawędź; `model_hole` z osią narzędzia mocowania):
    Ø, środek góry X/Y/Z, głębokość, przelotowy. Okrąg, który nie jest otworem
    sięgalnym z tego mocowania (czop, okrąg szkicu, otwór z boku), daje Ø albo R (łuk
    < 360°, np. zaokrąglenie), środek i oś;
  - prosta krawędź: długość i oś;
  - dwie ściany równoległe: odległość (np. „Distance along Z”); nierównoległe: kąt
    0–90° i najkrótsza odległość;
  - dwa otwory lub okręgi (decyzje usera): w **osiach ściany pierwszego okręgu**, Z na
    zewnątrz bryły (otwór sięgalny z mocowania: oś narzędzia; inny okrąg modelu:
    normalna płaskiej ściany, której jest krawędzią, przy dwóch ta bliższa narzędziu;
    okrąg szkicu: Z szkicu). Gdy narzędzie mocowania patrzy na tę ścianę, osie mocowania,
    a inaczej osie, jakie dałby tam Snap-0-Point (`frame.axes_for_normal`), i okno to
    pisze. Wyniki: odległość środków (przy równoległych osiach w poprzek osi), między
    najbliższymi punktami okręgów (tylko przy równoległych osiach: odległość osi − R1 − R2,
    okrąg w okręgu |R1 − R2| − odległość, przecinające się 0; ścianka do suwmiarki),
    **między najbliższymi punktami wzdłuż X i wzdłuż Y** (rzuty okręgów na oś; „overlap”,
    gdy na tej osi zachodzą na siebie), ΔX/ΔY/ΔZ od pierwszego klikniętego, oba Ø.
    Przy osiach nierównoległych dodatkowy wiersz „Shortest distance in space”
    (`distToShape` okręgów); tylko wtedy, jako uzupełnienie (user: najpierw „niewiele
    da”, potem „może to nie taki zły pomysł”, osobna linia). Pułapka: `ancestorsOfType` działa tylko na tym samym kształcie, z
    którego wzięto element (nowe `Part.getShape` daje `OCCError FindFromKey`).
  - ściana i otwór: przy osi równoległej do ściany odległość od ściany do środka oraz
    do bliższego i dalszego boku otworu; przy osi prostopadłej odległość wzdłuż osi do
    góry otworu; przy innych kąt i najkrótsza odległość;
  - inne pary: najkrótsza odległość (`distToShape`).
  Moje wybory (do potwierdzenia przez usera): kąt między ścianami 0–90°, ΔX/ΔY/ΔZ ze
  znakiem od pierwszego kliknięcia, środek otworu na jego górze. Etykiety budowane z
  części („Along ” + oś) jeszcze nie są gotowe do tłumaczenia.
- Okna nie blokują programu: można zaznaczyć coś innego i kliknąć pomiar jeszcze raz.
  Liczby z 3 miejscami, nigdy „-0.000”.
- Uwaga: klik w środek ściany z zerem trafia w trójnóg mocowania (Job), nie w ścianę.

## Symulacja

- CAM > Simulate (`handlers.simulate`, `ui/simulation.py`): **tymczasowo** symulator
  OpenGL FreeCADa (moduł `CAMSimulator`, okno „New CAM Simulator” z własnymi
  przyciskami play/pauza/krok/prędkość) sterowany wprost, bez panelu zadań FreeCADa
  (w AvangardeCam schowanego). Symuluje **aktywne mocowanie**: jego półfabrykat
  (świeży blok), detal (kompozyt klonów) i ścieżki FreeCADa aktywnych operacji, w
  układzie mocowania. Profile narzędzi bierze z `SimulatorGL.CAMSimulation.GetToolProfile`.
  Okno dostaje tytuł „Simulation - Setup N” i 70% okna programu, na środku.
- Nawigacja jak w widoku 3D AvangardeCam (styl Blender, decyzja usera): środkowy
  przycisk obraca, Shift+środkowy przesuwa, Ctrl+środkowy i kółko zoomują. Symulator
  FreeCADa sam obraca przy wciśniętym Alt, przesuwa z Shift i zoomuje z Ctrl+Shift
  przy ruchu myszy bez przycisku; filtr `_WindowFilter` nie przepuszcza środkowego
  przycisku, a jego przeciągnięcie wysyła jako takie ruchy. Prędkości symulatora są w
  pikselach, więc ruchy idą przez „wirtualny kursor” (`_speed`): przy przesuwaniu
  bryła idzie za kursorem (0,005 odległości oka na piksel w perspektywie 0,7 rad daje
  0,0069 × wysokość okna pikseli niezależnie od zoomu), obrót pół obrotu na szerokość
  okna (symulator: 0,01 rad/px), zoom Ctrl+środkowy jak FreeCAD (exp(10·px/wysokość))
  przy startowym zoomie. Kółko zostaje symulatora (przy dużym zbliżeniu skacze
  mocniej niż FreeCAD, zoom w środek okna, nie w kursor). Przeciągnięcie zaczyna się
  tam, gdzie zmieniają się klawisze, więc wciśnięcie i puszczenie środkowego wysyła
  ruch-reset (bez tego drugie przeciągnięcie bez ruchu myszy skakało).
- Do wymiany (user: „pewnie modyfikowana albo całkiem wymieniona”), więc nic poza
  `handlers.simulate()` nie zależy od tego modułu. Symuluje ścieżki FreeCADa, a nie
  program `.H` (dojazd XY-potem-Z i odjazd Z+40 robi dopiero postprocesor).
- Pułapka FreeCADa: `DlgCAMSimulator::resizeEvent` woła OpenGL bez `makeCurrent`,
  więc zmiana rozmiaru okna (także ręczna) trafiała w kontekst widoku 3D: widok 3D
  robił się czarny, a symulator gubił przyciski. `_ContextGuard` (filtr zdarzeń na
  oknie) ustawia kontekst symulatora przed każdym Resize. Kliknięcia w jego przyciski
  działają dopiero po ruchu myszy nad nimi (test wysyła MouseMove przed kliknięciem).

## Weryfikacja (Verify)

Stock z symulacji liczy `avangardecam/stocklab/`: **kopia** pakietu `stocklab/` z prywatnego
repo AvangardeCamLab (commit 6a1a576; tri-dexel w czystym Pythonie z numpy, opis i testy
biblioteki w tamtym repo). Kopii się tu nie poprawia: zmiana idzie w Labie, potem kopia
na nowo. Zastosowania (decyzja usera 2026-10-26): weryfikacja (pierwsza, 2026-10-27),
potem mocowanie nr 2 (stock po mocowaniu 1) i Adaptive na resztkach.

- **Przejściówka** (`model/verify.py`, czysty Python, testy `tests/test_verify.py` zwykłym
  `python3`): program NC mocowania (`model/nc.py`, to samo co dostaje postprocesor) →
  operacje biblioteki. Wszystko **w układzie mocowania**: stock to pudełko wzdłuż jego osi,
  narzędzie z +Z, więc działa każdy obrót zera.
- **Ruchy jak maszyna** (decyzja usera 2026-10-27), a nie ścieżki FreeCADa; od kroku
  „czas cyklu” we wspólnym `model/machine.py` (`Machine`, `machine_segments`, testy
  `tests/test_machine.py`), bo te same ruchy liczą Verify, czas i (później) odtwarzacz:
  - kompensacja RL/RR liczona jak TNC przy DR0: ruch włączający jedzie prosto do pierwszego
    punktu konturu, promień obok niego prostopadle do pierwszego elementu; elementy
    odsunięte o promień; róg zewnętrzny = łuk wokół punktu rogu, róg wewnętrzny = przecięcie
    odsuniętych elementów; ruch wyłączający jedzie prosto z ostatniego odsuniętego punktu.
    Za mały łuk lub odcinek (sterowanie by stanęło) = uwaga w wyniku. Test: program helisy
    z RL/RR po przeliczeniu to dokładnie droga środka narzędzia (`helix.moves(program=False)`);
  - cykl 205 jako ruchy: nad otwór na 2. odstępie (najpierw w górę, gdy niżej), w dół na
    odstęp, ostrze posuwem na głębokość, w górę; dziobanie nic więcej nie zbiera;
  - przejazdy między operacjami jak w `post/heidenhain.py`: po zmianie narzędzia Z100, po
    operacji Z40 (wycofanie maszyny), po wierceniu 2. odstęp; następna operacja jedzie w XY
    na tej wysokości, potem w dół.
- **Narzędzia** (`stock_tool`): część skrawająca o długości ostrza (bez niej 3 × Ø): Endmill
  walec, Ballend kula, Bullnose naroże, Drill stożek (bez kąta 118°), Chamfer/VBit stożek od
  średnicy czubka (bez kąta 90°), **frez do gwintów = walec średnicy zębów** (mój wybór).
  Szyjka i chwyt (nad długością ostrza) nie skrawają: osobno, w kolizjach niżej.
- **Kolizje** (`model/crashes.py`, wspólne dla Verify i Play; zgłoszenie usera 2026-10-28:
  plik usera, frez do gwintów M4 T217 — zęby Ø3,2 na 2,1 mm, szyjka Ø2,4 do 12,5 mm,
  chwyt Ø6 do 22 mm — gwint na -14, więc chwyt Ø6 wchodzi w otwór na 1,5 mm; symulator
  FreeCADa to pokazał, nasz nie, bo narzędzie było samym walcem zębów). Dwa rodzaje:
  `RAPID` = G0/FMAX zabiera materiał, `SHANK` = chwyt albo szyjka zabiera materiał.
  - `shank_tool(tool)`: szyjka (średnica i długość z narzędzia) i chwyt od niej do długości
    narzędzia (bez długości 2 × Ø nad ostrzem), średnicy chwytu (bez niej jak frez) — tak jak
    rysuje je odtwarzacz (`tool_profile`). **Tylko gdy narzędzie ma długość ostrza**
    (bez niej całe może skrawać: wiertło z biblioteki nie ma `CuttingEdgeHeight`).
  - `cut(stock, tool, shank, pieces)`: kawałki ruchów po kolei, jedną paczką
    (`cut_lines`, tak szybko jak samo cięcie); osobno, żeby zmierzyć objętość, tnie się ruch
    tylko wtedy, gdy materiał jest **na drodze**: na promieniach Z stocka w promieniu
    narzędzia od ruchu (widok z góry), między najniższym a najwyższym miejscem części
    narzędzia. Miejsce, gdzie narzędzie stoi na początku ruchu, należy do ruchu wcześniejszego,
    więc ruch prosto w górę patrzy tylko nad narzędzie, w dół tylko pod czubek. Ruchy w paczce
    czekają (tylko zabierają materiał): ruch „na drodze” sprawdzany jeszcze raz po ich
    docięciu. Pomiary na płycie testowej A (Medium): pierwsza wersja (zasięg + pół przekątnej
    komórki, bez tych dwóch reguł) łapała ścianki otworu helisy — 2837 z 2965 G0 cięte osobno,
    Play do końca 8,8 s zamiast 1,9 s; teraz 80 cięć osobno, Play do końca 3,9 s (najgorsza
    klatka bez zmian ~70 ms), a cięcie Verify **szybsze** niż `stocklab.simulate` (7,0 →
    2,7 s; ta sama lista G0 i ten sam stock — test `test_rapid_moves_as_the_stock_model_finds_them`).
  - Chwyt mierzony **węższy o 0,1 komórki** (`SHANK_SLACK_CELLS`), cięty pełny: chwyt
    szeroki jak frez, jadący helisą za ostrzem, zbierał to, co zostawiają cięciwy łuków
    (0,07 mm³ na pół obrotu przy 0,8 mm komórki) — kolizja z niczego.
  - Wynik na pliku usera: 18 kolizji chwytu (3 otwory × 5 półobrotów od -12,25 + odjazd do
    środka, ~10 mm³ na półobrót) w Verify i w Play. Test silnika `test_clean` (helisa Ø4 z
    biblioteki: ostrze 6, chwyt Ø6, w otworze Ø6 na wylot) okazał się prawdziwą kolizją chwytu
    i teraz jej oczekuje.
- **Sprawdzanie**: G0 w materiał i chwyt w materiale (objętość, gdzie; `crashes.simulate`
  zamiast `stocklab.simulate`), za głęboko jednym sprawdzeniem całego
  programu, w raporcie osobno dla każdej operacji (`Gouges.operation`: która weszła najgłębiej
  w punkt; najgłębsze miejsce i liczba punktów), kolory stocka z biblioteki (szary = detal,
  niebieski = zostawiony materiał, czerwony = za głęboko). Tolerancja 0,01 mm, punkty detalu
  dwa razy rzadziej niż komórki stocka. Zostawiony materiał najciemniejszy już przy
  **3 komórkach** nad detalem (`LEFTOVER_CELLS`; domyślne 25 komórek biblioteki liczyło
  ~3,5 min na detalu testowym przy 120, bo siatka z STEP-a ma dziesiątki tysięcy trójkątów). **Frezowanie gwintów nie jest sprawdzane na za
  głęboko** (mój wybór: gwint wychodzi poza otwór modelu, który ma średnicę rdzenia).
  Wiercenie jest sprawdzane: wiertło ze stożkiem w otworze modelu z płaskim dnem świeci na
  czerwono.
- **Gwint bez otworu** (zgłoszenie usera 2026-10-27, jego płyta: frez do gwintów w
  otworze, którego program nie wywiercił — Verify milczał, bo walec freza po prostu
  „wyfrezował” otwór, a gwinty nie są sprawdzane na za głęboko). Frez do gwintów skrawa
  tylko zębami, więc w środku, w średnicy rdzenia gwintu, otwór musi być już pusty. Każdy
  otwór frezowania gwintów (`PlannedHole`: środek helis, dno, zasięg; ruchy posuwem
  przypisane do najbliższego środka) dostaje **własny drobny stock** wokół otworu (od dna do
  góry stocka, `BODY_CELLS` = 10 komórek na promieniu rdzenia freza — niezależnie od
  wybranej dokładności: otwór M3 to dwie komórki stocka Rough), wycina się z niego
  operacje wcześniejsze (tylko ruchy, których pudełko sięga otworu: ~0,1 s na otwór), potem
  ruchy posuwem w otworze **rdzeniem freza**: walec o promieniu freza minus głębokość zębów
  (5/8 H, H = P / (2 tan(kąt/2)), kąt z narzędzia, bez niego 60°; dla M3 rdzeń sięga średnicy
  2,4587 = MinorDiameter FreeCADa) minus jedna cięciwa łuków (`CHORD` komórek: ściany otworu
  frezowanego helisą są w stocku cięciwami). Materiał zabrany przez rdzeń (ponad
  `TOUCH` komórki) = otwór niewywiercony albo za mały albo za płytki (`HoleCheck`, objętość
  w mm³; ramka raportu „Threads without their hole”, otwór i jego okolica na czerwono).
  Sprawdzone na pliku usera (oba otwory M3, 26,9 mm³ każdy, Rough i Medium) i na
  wariantach: Ø2,5 i Ø2,46 na -8 i Ø2,5 na -6,8 czyste; Ø2,5 na -6 (stożek wiertła pod
  końcem freza), Ø2,3 i Ø2,0 wykryte (Ø2,4 ledwo: 0,04 mm³).
- **Silnik** (`engine/verify.py`): `prepare(job)` w wątku FreeCADa: program mocowania z
  `nc_program` (ten sam co eksport, więc błąd operacji innego mocowania też zatrzymuje),
  narzędzia z ToolControllerów, detal = klony modelu z Joba (już w układzie mocowania)
  `tessellate` z ugięciem 0,005 mm (połowa tolerancji: cięciwy otworu nie udają wejścia w
  ścianę; 0,001 mm na płycie płycie testowej A = 27 s i 351 tys. trójkątów, 0,005 = 1,8 s i
  85 tys.); trójkąty zapamiętane, dopóki kształty klonów są te same (kolejny Start ich nie liczy). `run(prepared, resolution)` nie dotyka FreeCADa (może iść w tle).
- Czas (detal testowy 40×20×12, dwie helisy Ø4, 246 ruchów, 70 tys. trójkątów): przy 120
  kilkanaście sekund; przy 500 samo cięcie 91 s (każdy krok helisy to rampa, a komórka
  0,09 mm), zostawiony materiał ~75 s.
- **Okno** (CAM > Verify w grupie Output, w miejscu dawnego placeholdera „Check”;
  `handlers.verify`, `ui/verify.py`): niemodalne, w prawym górnym rogu pod wstążką (detal
  zostaje widoczny). Okno otwiera się **od razu**, nic jeszcze nie liczy, i czeka na wybór
  dokładności i **Start** (decyzje usera 2026-10-27: przycisk nie może od razu liczyć, okno
  ma być natychmiast; wcześniej przed oknem szło przeliczenie dokumentu 8 s i trójkąty 27 s).
  Start: przeliczenie dokumentu i `prepare` w wątku FreeCADa (okno najpierw pokazuje krok
  „Reading the program and the part”), potem cięcie w tle. Dokładność: Rough 150 / Medium 250 (na start) / Fine 500
  komórek, ostatnia zapamiętana (`LastVerifyResolution`); Start liczy też od nowa.
  **Export...** (po wyniku): stock z symulacji jako `.ply` z kolorami (Blender, MeshLab) albo
  `.stl` sam kształt (`model.verify.export`); folder zapamiętany (`LastVerifyExportDir`). Cięcie w osobnym wątku Pythona (`engine.verify.run` nie dotyka
  FreeCADa), okno pokazuje krok i pasek „zajęty”. Raport: za głęboko dla każdej operacji
  (ile, gdzie, ile punktów), G0 w materiał, chwyt lub szyjka w materiale („Shank or neck in
  material”, tylko gdy są), gwinty bez otworu (albo „Every thread has its
  hole.”, gdy są gwinty), uwagi kompensacji, rozmiar komórki; legenda kolorów. Bez operacji: komunikat na pasku stanu, jak Simulate.
- **Widok 3D** (decyzja usera 2026-10-27): stock z symulacji **zamiast** detalu, stocka i
  ścieżek aktywnego mocowania, dopóki okno jest otwarte; zamknięcie przywraca widok
  (`scene.apply`). Węzeł Coin (`SoIndexedFaceSet` z kolorami wierzchołków) wstawiony w każdy
  widok 3D **przed** transformacją mocowania (`scene._FRAME_NAME`): stock jest w układzie
  mocowania, w którym rysowany jest widok. Szkice zostają widoczne.
- Czas na detalu testowym (40×20×12, kontur T21 po obrysie): Medium 36 s, Rough 19 s.
- Na razie świeży blok aktywnego mocowania (mocowanie nr 2 później).

## Czas cyklu

Decyzja usera 2026-10-27: przed mocowaniem nr 2 własny symulator (odtwarzacz ruchów
w widoku 3D: lista operacji, przyspieszanie/zwalnianie, ←/→ ruch po ruchu, ↑/↓ operacja,
coś się ma usuwać, symulator FreeCADa zostaje na razie obok), a jako pierwszy krok
szacowanie czasu operacji i całego mocowania.

- **Ruchy** z `model/machine.py` w pełni (`Machine(full=True)`): jak w Verify plus droga w
  górę na Z100 przed zmianą narzędzia i **cykl 205 tak, jak go jedzie TNC 620**: pogłębiony
  start (Q379) posuwem Q253, dziobnięcia Q202 malejące o Q212, nie mniej niż Q205 (`pecks`),
  łamanie wióra co Q257 (w górę o Q256 i z powrotem, szybko), po dziobnięciu szybko na
  odstęp Q200 i w dół na odstęp wyprzedzenia nad osiągniętą głębokością (Q258 przy
  pierwszym, Q259 przy ostatnim, równo pomiędzy), postój Q211 na dnie, w górę szybko (Q208
  program nie pisze: przyjęte FMAX). Verify zostaje przy wierceniu na raz (dziobanie nic
  nie zbiera).
- **Czas** (`model/cycle_time.py`, czysty Python): posuw = długość drogi **środka narzędzia**
  (kompensacja przeliczona: TNC trzyma posuw środka; gwint M3 Ø2,4 jedzie po helisie R0,3,
  nie R1,5) / F, ruch bez F trzyma poprzedni (jak program); G0 = najwolniejsza oś
  (`max(|dx|, |dy|)/43000, |dz|/36000` mm/min — user 2026-10-27, karta katalogowa podaje 48
  m/min XY); postój Q211 × otwory; zmiana narzędzia 1,5 s (karta: T-T) w operacji, która
  woła narzędzie. Koniec programu (wyłączenie wrzeciona, odjazd stołu) nie jest liczony.
- **Dynamika maszyny** (`_dynamic_times`, od kalibracji 2026-10-27): ruchy cięte na proste
  kawałki (łuki cięciwami co 5°, bez zwalniania między nimi, na łuku najwyżej `sqrt(a·R)`),
  prędkość na narożu jak okrąg przez naróż w tolerancji (junction deviation:
  `sqrt(a·δ·s/(1−s))`, s = sin połowy kąta), stop przy zawracaniu i na końcach operacji,
  planowanie wstecz i w przód w granicach przyspieszenia a; na ruchach posuwem każde
  rozpędzanie i hamowanie (przez ile trzeba kawałków) dłuższe o szarpnięcie j (krzywa S),
  na FMAX bez szarpnięcia (`rapid_jerk_mm_s3` = 0). **Kalibracja** na symulacji TNC (user):
  - `Test_czasu.H` = eksport płyty usera bajt w bajt; symulacja całości 23:43, prawdziwy
    przebieg 23:52; programy po jednej operacji: Facing 1:14, Drilling 0:41 (dziobanie po
    1 mm), Adaptive 21:23 (42 tys. kawałków, mediana 0,4 mm, F1250), gwint 0:26. Przy pełnej
    prędkości liczyliśmy 1:08 / 0:18 / 17:58 / 0:22 (19:47, −17 %).
  - Programy kalibracyjne (FMAX tam i z powrotem w powietrzu, pętla `LBL 1` / `CALL LBL 1
    REP`): 500 × 2 mm w Z 0:31, 300 × 10 mm 0:41, 100 × 100 mm 0:45, 500 × 2 mm w X 0:31,
    100 × 300 mm w X 1:17. Z jak X; same przyspieszenie 2,1 m/s² bez szarpnięcia pasuje do
    wszystkich w 3 % (pierwsze dopasowanie tylko do płyty dało 3 m/s² z szarpnięciem także
    na FMAX: krótkie ruchy 56 s zamiast 31, wiercenie 49 s zamiast 41).
  - Dopasowane razem (siatka, ten sam kod): **a = 2,1 m/s², j = 100 m/s³ na posuwie,
    δ = 0,002 mm** → płyta 1:13 / 0:43 / 21:32 / 0:24, razem 23:53 (z 1,5 s na zmianę
    narzędzia). Ruchy posuwem potrzebują szarpnięcia i naroży (bez nich Adaptive −8 %).
    Gwint zostaje 3 s za krótki (helisa półobrotami CP: TNC chyba zwalnia między blokami).
    Zwykły mnożnik byłby zły: długie ruchy prawie nic nie tracą, krótkie FMAX nawet 20 razy
    dłużej niż przy pełnej prędkości. Liczenie dynamiki na płycie: 0,2 s (Adaptive).
- **Silnik** (`engine/cycle_time.py`): `program_times(doc)` z `nc_program` (ten sam program co
  eksport, aktywne operacje). Płyta usera (4 operacje, Adaptive 25 tys. ruchów): program
  0,2 s + czas 0,13 s; wynik 12 min 25 s (FreeCAD w swoim CycleTime: 17 min 18 s).
- **Liczone tylko na żądanie** (decyzja usera 2026-10-27: liczenie przy każdym spojrzeniu
  przy wielu ruchach zamuli program; płyta usera po zmianach Adaptive: 36 tys. ruchów,
  program 1,65 s + czas 0,15 s). W tle na innym rdzeniu nie: ścieżki FreeCADa czyta się tylko
  w głównym wątku, a to większość kosztu.
- **Okno** (`ui/cycle_time.py`): CAM > Output > **Cycle time** (stoper,
  `Resources/icons/AvangardeCam_CycleTime.svg`) otwiera okno z tabelą wszystkich mocowań
  (pogrubione, z sumą) i ich operacji: narzędzie, czas, posuw, szybkie, postój, zmiana
  narzędzia; operacja wyłączona szara „switched off”; Recalculate, Copy (tabela do schowka,
  tabulatory: do arkusza albo do kalibracji). Wiersz **Time** w szczegółach mocowania i
  każdej operacji (jedna linijka w `project_panel._show_item`) niczego nie liczy: pokazuje
  ostatni wynik („1 min 05 s (feed 52 s, rapid 11 s, tool change 1.5 s)”), a bez niego link
  „Work it out”. Czasy dokumentu pamiętane do najbliższej zmiany w nim (własny obserwator;
  ukrycie operacji — `Visibility` i `_GroupTouched` grupy — się nie liczy); po zmianie
  wiersz pisze „changed since it was worked out”, okno szarzeje tabelę i prosi o Recalculate.

## Symulacja w osobnym oknie (Play)

Kroki 2 i 3 własnego symulatora (decyzje usera 2026-10-27/28): program aktywnego mocowania
odtwarzany tak, jak go wykonuje maszyna, ze stockiem, z którego ubywa materiału, **w osobnym
oknie** (pierwsza wersja leżała nakładkami na widoku projektu; user: nachodziła na karty
dokumentów, przezroczysta lista na jego motywie, brak listy programu i bryły stocka → osobne
okno, widok projektu nietknięty). Symulator FreeCADa (CAM > Simulate) zostaje na razie obok.
Mocowanie nr 2 to krok 4.

- **Model ruchów w czasie** (`model/playback.py`, czysty Python z numpy, testy
  `tests/test_playback.py` zwykłym `python3`): `timeline(setup, setup_index, lines, lines_of)`
  → `Timeline`.
  - Ruchy: te same co Verify i czas cyklu (`model/machine.py`, `Machine(full=True)`:
    dziobanie cyklu 205, droga na Z100 przed zmianą narzędzia, kompensacja RL/RR jak TNC).
  - Czas każdego ruchu: `cycle_time.segment_times` (dynamika maszyny jak w czasie cyklu;
    `_dynamic_times` liczy teraz czasy kawałków w `_piece_times` i je sumuje, wyniki bez
    zmian). Cały czas mocowania = jego czas cyklu (test pilnuje; płyta usera 23:52).
  - **Krok** (`Step`) = jeden blok programu, czyli jeden `Element` maszyny (ruch z
    kompensacją może mieć kilka odcinków: łuk na rogu zewnętrznym należy do ruchu po rogu),
    a do tego zmiana narzędzia (`TOOL_CHANGE`: 1,5 s postoju, nowe narzędzie) i postój
    cyklu wiercenia na dnie otworu (`DWELL`, Q211). Droga w górę na Z100 przed zmianą
    jedzie jeszcze starym narzędziem.
  - W obrębie odcinka narzędzie jedzie równo przez jego czas (przyspieszanie i zwalnianie
    są tylko w tym, ile trwa). Pozycja w chwili t: `position(t)` (łuk i helisa: promień i
    wysokość równo między końcami).
  - Na końcu kroku nadal „trwa” ten krok (`step_at`: ostatni zaczęty przed t), jak TNC
    pracujące blok po bloku pokazuje blok właśnie wykonany. ←/→ (`next_stop`,
    `previous_stop`) skaczą po końcach kroków; kroki bez czasu (np. dojazd w XY, gdy
    narzędzie już tam jest) są pomijane. ↑/↓ (`next_operation`, `previous_operation`): początek
    następnej operacji / bieżącej (na samym początku: poprzedniej).
  - Ścieżka operacji do rysowania: `operation_polyline` (łuki jako cięciwy co najwyżej
    0,01 mm od łuku i co najwyżej 10°), `Polyline.done(odcinek, udział)` = ile punktów już
    przejechane. Kształt narzędzia: `tool_profile` (część skrawająca jak w Verify: długość
    ostrza albo 3 × Ø, kula, naroże, stożek wiertła 118°, fazownik; szyjka freza do gwintów;
    chwyt do długości narzędzia, bez niej 2 × Ø wyżej), `revolve` → trójkąty.
- **Materiał** (`model/playback_stock.py`, `Material`, testy w `tests/test_playback.py`): stock
  mocowania cięty biblioteką stocklab jak w Verify (pudełko stocka, część skrawająca
  `verify.stock_tool`, narzędzie z +Z, układ mocowania). `cut_to(t)`: do przodu tnie tylko to,
  co narzędzie przejechało od ostatniego razu (odcinek, na którym jest, do miejsca narzędzia;
  kawałek łuku krótszy niż 0,001 mm jako odcinek prosty, bo stocklab bierze łuk kończący się
  tam, gdzie zaczyna, za cały okrąg); do tyłu wraca do kopii stocka zapamiętanej co
  `SNAPSHOT_SEGMENTS` = 2000 odcinków (i na starcie) i tnie od niej. Wszystkie ruchy jednego
  narzędzia cięte **naraz** przez `crashes.cut` (łuki cięciwami jak w `simulate`), które przy
  okazji łapie G0 w materiał i chwyt w materiale (osobno tnie tylko ruchy z materiałem na
  drodze); `Material.crashes` = {(rodzaj, odcinek): mm³}, znalezione raz, po cofnięciu nie
  liczą się podwójnie; `played_crashes` daje je na osi czasu (krok, wiersz programu). Testy:
  cięcie kawałkami = cięcie od razu, cofanie z kopii = cięcie od zera, G0 w blok zabiera
  materiał i jest znaleziony, chwyt przy ruchu w bok (nie przy zejściu posuwem: ostrze idzie
  pierwsze), dobry program bez kolizji.
  **Kawałki** (2026-10-29, prośba usera: przy trudniejszym detalu symulacja nie nadawała się
  do użycia): stock jest obserwowany (`stocklab Stock.watch`), więc każde cięcie notuje obrys
  zmienionych komórek. `changed_pieces()` zwraca `(all, pieces)`: za pierwszym razem
  wszystkie kawałki powierzchni (`stocklab.mesh.pieces`, `PIECE_CUBES` = 32 sześciany), potem
  tylko te, w których mógł się zmienić materiał. Każde cięcie trafia do `_history` jako (od,
  do, komórki). Przy cofaniu zmienione są komórki cięć, które kończyły się po nowym czasie
  (tego cięcia już nie ma). To, co jest cięte ponownie od kopii aż do nowego czasu, jest takie
  samo jak narysowane, więc nie trafia do zmienionych. Test: granie po kawałku, cofanie
  z kopii i skoki zawsze dają złożone kawałki = `stocklab.surface` stocka w tej chwili.
- **Wiersz programu** (`post/heidenhain.numbered(program)`): te same wiersze co `write()`
  (test: tekst bajt w bajt) i słownik `{(mocowanie, operacja) + źródło: indeks wiersza}`.
  Źródło ruchu ma też `Element.source` w `model/machine.py`: `("change",)` droga na Z100
  (pierwszy blok końca narzędzia, `L Z100 R0 FMAX`), `("call",)` TOOL CALL, `("approach",)`
  nad pierwszy punkt, `("move", i)` ruch `op.moves[i]`, `("retract",)` / `("off",)` odjazd
  na Z40 i wyłączenie kompensacji, `("hole", k)` cały cykl w otworze k (wiersz CYCL CALL
  POS). Ruch, który w programie nic nie zmienia, nie ma wiersza: krok pokazuje wiersz
  poprzedni. Program liczony dla wszystkich mocowań, więc numery są jak w eksporcie.
  `machine_segments(…, owners=[])` podaje, do którego elementu należy każdy odcinek.
- **Silnik** (`engine/playback.py`): `prepare(job)` = `nc_program` (nazwa z etykiety
  dokumentu), `numbered`, `timeline`, narzędzia mocowania, pudełko stocka, detal jako trójkąty
  (klony Joba, ugięcie 0,02 mm: do oglądania). Błąd programu → `ProjectError`.
- **Widok 3D okna** (`ui/coin_view.py`, `CoinView`): własny `QOpenGLWidget` rysujący scenę
  Coin przez `SoRenderManager` (Quarter z pivy się nie ładuje: jego nakładka Qt nie ma
  `QtOpenGLWidgets` w Qt 6), własny kontekst pamięci podręcznej GL, kamera ortograficzna,
  światło od oka i słabsze z tyłu. Nawigacja jak w widoku AvangardeCam (Blender): środkowy
  obraca (wokół Z świata i poziomu ekranu, Z zostaje w górze), Shift przesuwa, Ctrl zoomuje,
  kółko zoomuje do kursora; lewy robi to samo (nie ma tu czego zaznaczać, a touchpad
  laptopa nie ma środkowego). Przyciski Isometric/Top/Front/Right/Fit; Fit kadruje pudełko
  stocka i zero (nie narzędzie na Z100).
- **Okno** (CAM > Output > **Play**, `handlers.play`, `ui/playback.py`, `SimulationWindow`,
  ikona `AvangardeCam_Play.svg`): osobne okno („Simulation - Setup 1”, 80% ekranu, na środku;
  można zmaksymalizować albo dać na drugi monitor). U góry: kierunki widoku, Stock / Part
  (detal przezroczysty, na start wyłączony) / Path, dokładność Rough 150 / Medium 250 / Fine
  500 komórek (`LastPlaybackResolution`), rozmiar komórki i czas ostatniego rysowania stocka.
  W środku widok 3D; po prawej operacje z narzędziem i czasem (klik = początek operacji,
  bieżąca pogrubiona) i **cały program .H** (`QListWidget`, czcionka o stałej szerokości,
  wiersze innych mocowań szare, bieżący wiersz podświetlony i na środku; klik w wiersz = tam,
  gdzie ten blok się wykonał; wiersz bez bloku = początek następnego). Na dole oś czasu
  (operacje tak długie, jak trwają; przebyta część ciemniej; klik/przeciągnięcie = skok,
  stock liczony po puszczeniu), przyciski ⏮ ◀ ▶/❚❚ ▶ ⏭,
  prędkość ×0,1…×100 (`LastPlaybackSpeed`), zegar, narzędzie, posuw/FMAX/Tool change/Dwell.
- **Scena**: stock (kawałki `Material.changed_pieces`, każdy z własnym `SoSeparator` z
  `SoCoordinate3` i `SoIndexedFaceSet` pod wspólnym materiałem, podmieniane tylko zmienione,
  puste usuwane; nowy `Material` po zmianie dokładności = wszystkie od nowa), detal (przełącznik), pudełko stocka, krzyż osi
  w zerze, ścieżka **tylko bieżącej operacji** w `SoAnnotation` (widać ją przez materiał:
  przebyte posuwy niebieskie, FMAX w kolorze FreeCADa, reszta blado; jedna `SoCoordinate3`,
  przebyte = `numVertices`, reszta = `startIndex`), narzędzie (część skrawająca pomarańczowa,
  chwyt szary). Siatki do Coin prosto z tablic numpy (`setValues` z float32/int32).
- **Klawisze** (filtr zdarzeń aplikacji, tylko gdy okno symulacji jest aktywne i nie w polu do
  pisania): spacja play/pauza, ←/→ blok, ↑/↓ operacja, Home/End, Esc zamyka.
- **Rysowanie stocka w trakcie** (decyzja usera: na żywo, ale zmierzyć): przy odtwarzaniu
  stock cięty i rysowany od nowa najwyżej co `MESH_MS` = 100 ms i najwyżej połowę czasu
  (odstęp ≥ 2 × czas ostatniego rysowania), narzędzie co 20 ms; klatka gra najwyżej 0,1 s
  czasu rzeczywistego (za wolny komputer gra wolniej zamiast skakać i ciąć coraz więcej
  naraz); wiersz programu zaznaczany najwyżej co 100 ms (zaznaczenie na liście 40 tys.
  wierszy ~7 ms); przy pauzie, kroku i skoku zawsze dokładnie tam, gdzie narzędzie (kursor
  oczekiwania). Pomiary na laptopie usera (i5-4200H; okno w Xephyr, czyli OpenGL programowy:
  klatka widoku 14–30 ms, na karcie graficznej mniej):
  - płyta usera 303×96×20 przy Medium (komórka 1,22 mm): otwarcie 3 s, skok na środek
    Adaptive 1 s, cofnięcie o 10 min 0,14 s, rysowanie stocka 80–135 ms (siatka ~40 ms +
    przekazanie do Coin ~35 ms + cięcie), przy ×100 stock ~2,3 razy na sekundę;
  - detal testowy 42×22×13 (zwarty blok: 250×131×77 komórek) przy Medium: 230–330 ms (siatka
    150 ms, 233 tys. trójkątów + Coin 80 ms); Rough 35 + 27 ms; Fine 1,3 s;
  - koszt siatki rośnie z liczbą wszystkich komórek (stocklab liczy powierzchnię całego
    stocka za każdym razem), przekazanie do Coin z liczbą trójkątów (pivy kopiuje element po
    elemencie, ~50 ns; `setValuesPointer` nie przyjmuje tablic numpy). Kierunek: siatka
    kawałkami, od nowa i do Coin tylko tam, gdzie narzędzie cięło — ZROBIONE (niżej).
  - **po kawałkach (2026-10-29)**, detal testowy B (27×20,5×20,5, 7647 odcinków, 4:11),
    granie ×10 od 30% programu przez ~8 s w Xephyr:
    - Medium: siatka zmienionych kawałków 24 ms + Coin 13 ms (było: cała siatka 303 ms + Coin
      166–216 ms); stock narysowany 4–5 razy w 8 s (było: raz na 9,7 s);
    - Fine: kawałki 126 ms + Coin 54 ms (było: 1,8 s + 0,7–1,7 s);
    - teraz najdroższe są: cięcie, które przy ×10 obejmuje kilka sekund programu (Medium
      ~27 ms na sekundę programu, Fine ~107 ms), oraz rysowanie samej sceny przez programowy
      OpenGL Xephyra (Medium ~100 ms na klatkę przy 500 tys. trójkątów, Fine ~420 ms przy
      2 mln); na prawdziwej karcie graficznej rysowanie powinno być dużo szybsze, a Coin
      trzyma w pamięci podręcznej kawałki, które się nie zmieniły;
    - dalsze możliwości: scalanie płaskich fragmentów siatki (mniej trójkątów do rysowania) i
      ewentualnie rdzeń w C++ dla siatki kawałka i cięcia (decyzja usera 2026-10-29: najpierw
      kawałki w Pythonie, C++ dopiero po pomiarze).
- **Kolizje w oknie** (prośba usera 2026-10-28 „wyłapywanie G0 w symulacji”): znalezione,
  gdy stock zostaje pocięty do danego miejsca (więc pojawiają się w trakcie grania; Verify
  znajduje wszystkie naraz). Każda = czerwona kreska na osi czasu, czerwone tło wiersza .H,
  przycisk obok posuwu („⚠ 1 of 9: FMAX into material: block 77 (65.0 mm³)”, „Shank in
  material”; podpowiedź = lista; klik = koniec bloku następnej kolizji, po ostatniej
  pierwsza). Przy graniu zatrzymuje się na końcu bloku każdej kolizji (nowej i znanej).
  Zmiana dokładności liczy od nowa (kolizje też).
- Okno zamyka się: Esc / zamknięcie okna, zamknięcie dokumentu (obserwator), wyjście z
  AvangardeCam (`workbench.Deactivated`). Dane to migawka z chwili otwarcia: zmiana operacji
  wymaga otwarcia okna od nowa.

### Pułapki FreeCADa (sprawdzone)

- `Shape.optimalBoundingBox(True, …)` korzysta z triangulacji wyświetlania i w GUI
  powiększa pudełko o jej odchyłkę (zero wyszło na Z 12.016 zamiast 12). Używamy
  `optimalBoundingBox(False, False)`.
- `doc.removeObject()` na ToolBicie zostawia jego bryłę kształtu (Body, Sketch,
  Revolution, Origin), bo sprząta ją dopiero `onDelete` z drzewa. Dlatego
  `_remove_bit` usuwa `BitBody` sam. Dotyczy to też domyślnego freza 5 mm z nowego
  Joba. Pliki z etapu 2 mogą mieć takie sieroty, ale lista szkiców pomija szkice
  wewnątrz brył.
- Etykiety w dokumencie są unikalne. Ten sam T21 w drugim mocowaniu dostaje
  etykietę „… (Setup 2)”, a nazwę narzędzia czytamy z `AvangardeToolName`, nie
  z etykiety.
- `Face.normalAt` w 1.1 zwraca już normalną na zewnątrz dla ścian Reversed (kod
  Joba FreeCADa odwraca ją drugi raz). `geometry.outward_normal` sprawdza kierunek
  punktem próbnym.
- `Gui::QuantitySpinBox` z maksimum po cichu zostawia starą wartość, gdy wpisana
  jest poza zakresem. Dlatego pola Z-Depth i Start Z przyjmują każdą liczbę, a
  zakres i kolejność sprawdza model.
- `viewFront()` animuje kamerę, a `fitAll()` w trakcie animacji kadruje źle
  (w testach trzeba odczekać).

## Interfejs

```
┌──────┬─────┬─────┬─────┬───────────────────────────────────────────────┐
│ File │ ↶ ↷ │ CAD │ CAM │                                               │  zakładki
├──────┴─────┴─────┴─────┴───────────────────────────────────────────────┤
│  [grupa] [grupa] [grupa] …  funkcje programu z aktywnej zakładki        │  wstążka
├────────────────────┬───────────────────────────────────────────────────┤
│ Project            │                                        ┌───────┐  │
│  ▸ Model           │                                        │ kostka│  │
│  ▸ Stock           │                                        │ widoku│  │
│  ▸ Tools           │            podgląd 3D                  └───────┘  │
│  ▸ Operations      │                                                   │
├────────────────────┤                                                   │
│ Details            │                                                   │
│  właściwości       │                                                   │
│  zaznaczonej       │                                                   │
│  pozycji           │                                                   │
├────────────────────┴───────────────────────────────────────────────────┤
│ pasek stanu (FreeCAD: współrzędne, jednostki)                           │
└────────────────────────────────────────────────────────────────────────┘
```

- **File** (lewy górny róg): menu plików, eksport programu NC, ustawienia i przejście do
  pełnego FreeCADa.
- **Undo / Redo** (obok File): to akcje `Std_Undo` / `Std_Redo` FreeCADa podpięte pod
  przyciski (`ribbon.HistoryButton`), więc skróty Ctrl+Z / Ctrl+Shift+Z, stan
  aktywności i historia są FreeCADa; podpowiedź podaje nazwę cofanego kroku. Cofa się
  to, co zmienia dokument w jednej transakcji (`openTransaction` … `commitTransaction`),
  i **każda nowa funkcja zmieniająca dokument musi robić to w jednej transakcji**. Poza
  undo zostają: tworzenie narzędzi (patrz Pułapki), ustawienia w `params()` (ostatnio
  użyte wartości okien), zaznaczenie, ukrycie w 3D i symulacja.
- **CAD / CAM**: zakładki wstążki. Pod nimi grupy przycisków z funkcjami programu
  (to nie są narzędzia CNC).
- **Lewy panel**: u góry lista projektu (model, półfabrykat, narzędzia, operacje), pod
  nią szczegóły zaznaczonej pozycji.
- **Podgląd 3D**: widok FreeCADa, a w prawym górnym rogu jego kostka nawigacyjna (NaviCube).
- **Okna operacji** (Contour, Drilling, Thread milling, Adaptive, Facing) wołają
  `ui/window_fit.fit_contents`. Pułapka Qt: nowe okno ma najwyżej 2/3 wysokości ekranu
  (1080 → 720 px), a okno z zawijanymi etykietami (długie opisy) nie dostaje minimalnej
  wysokości, więc wiersze były zgniecione poniżej swojej wysokości (Choose tool... 9 px,
  bez napisu, podpowiedź pod listą znikała). `fit_contents` trzyma minimalną wysokość =
  potrzebna dla szerokości (najwyżej ekran − 80 px), a gdy nie mieści się na ekranie,
  otwiera okno szerzej (do 900 px). Na ekranie 768 px okno Contour nadal się nie mieści
  (do zrobienia: przewijanie).
- **Obrazki pól** (pomysł usera, `ui/field_pictures.FieldPictures`, na razie okno
  Contour): obok pól obrazek tego, co robi pole, w którym jest użytkownik (klik albo
  Tab). Przy otwarciu i w polach bez własnego obrazka obrazek startowy okna
  (`contour_start.svg`, narysowany przez Claude'a w stylu obrazków usera: stopień,
  linie konturu, kierunek, narzędzie przy ścianie, Start Z i Z-Depth). Z step i Order:
  kolejność przejść wybrana w Order (`contour_order_by_pass.svg` = „naprzemiennie
  góra–dół”, `contour_order_by_level.svg` = „najpierw góra, potem dół”: kolumny =
  przejścia XY, wiersze = poziomy Z, numery = kolejność; obrazki usera z
  własne grafiki wektorowe, bez zmian). Pliki w
  `Resources/images` (560 × 400, rysowane 350 × 250, SVG Tiny, bo QSvgRenderer).

### Tryb kiosku i tryb eksperta

AvangardeCam jest workbenchem FreeCADa. Po aktywacji chowa menu, paski i panele
FreeCADa i pokazuje własny układ. `File → FreeCAD (expert mode)` przełącza na
workbench CAM i przywraca pełny FreeCAD. Powrót odbywa się przez wybór workbencha
AvangardeCam. Przy zamykaniu programu układ FreeCADa jest przywracany przed zapisem
stanu okna, więc pełny FreeCAD nigdy nie zostaje „rozebrany”.

### Język

Teksty w kodzie są po angielsku i przechodzą przez
`translate("AvangardeCam", …)` (`avangardecam.tr`). Tłumaczenie robi się standardowo:
`lupdate` → `translations/AvangardeCam_xx.ts` → Qt Linguist → `.qm`.

## Struktura katalogów

```
src/Mod/AvangardeCam/
  ARCHITECTURE.md        ten dokument
  CMakeLists.txt         kopiowanie do build/Mod i instalacja
  Init.py, InitGui.py    rejestracja w FreeCADzie
  Resources/icons/
  Resources/images/      obrazki pól okien operacji (ui/field_pictures.py)
  avangardecam/
    __init__.py          ścieżki, parametry, tr()
    workbench.py         workbench FreeCADa (kiosk on/off)
    profile.py           ustawienia profilu (start w AvangardeCam, kolory zaznaczenia)
    actions.py           katalog funkcji: zakładki, grupy, przyciski, menu File
    ui/                  wstążka, menu File, lista projektu + szczegóły, układ okna,
                         widok 3D mocowań (scene.py), zaznaczanie linii szkicu
                         (picking.py), strzałki kierunku (direction.py), okna operacji
                         (contour, drilling, thread, adaptive, facing), symulacja (simulation.py,
                         symulator FreeCADa), symulacja w osobnym oknie (playback.py,
                         własny widok 3D coin_view.py)
    model/               opis projektu: jednostki, narzędzia, półfabrykat, punkt zerowy
                         (frame.py), operacje (operations.py), dojazd i odjazd
                         przy kompensacji (leads.py), ruchy gwintów (threads.py) i
                         Adaptive (clearing.py), ruchy maszyny (machine.py), czas cyklu
                         (cycle_time.py), ruchy w czasie (playback.py), materiał w czasie
                         (playback_stock.py), kolizje G0 i chwytu (crashes.py), stock
                         z siatki dla następnego mocowania (start_stock.py); czysty Python
    engine/              tłumacz na FreeCAD CAM (freecad_cam.py), geometria detalu (geometry.py),
                         proxy operacji FreeCADa (contour, drilling, thread_milling, adaptive),
                         pomiar (measure.py, osobny, tylko czyta)
    post/                postprocesory: neutralny program NC (model/nc.py) → tekst
                         sterowania (heidenhain.py: TNC 620 Klartext .H)
    tests/               testy modelu i postprocesora (python3) oraz tłumacza
                         (FreeCADCmd, run.py)
  tests_gui/             testy GUI (Xephyr + zrzuty ekranu)
```

## Etapy

1. **Layout**: wstążka File/CAD/CAM, lista i szczegóły, podgląd 3D z kostką, tryb
   kiosku i eksperta. Funkcje to placeholdery. Działają tylko pliki
   (New/Open/Save/Import STEP) i przejście do FreeCADa.
   Placeholdery (akcje bez `handler` w `actions.py`) zostają w katalogu, ale wstążka
   i menu File ich nie pokazują (`actions.shown_tabs` / `shown_file_menu`): przycisk,
   który nic nie robi, tylko myli użytkownika. Grupa albo zakładka bez działającego
   przycisku znika razem z nimi. Przycisk pojawia się sam, gdy dostanie handler.
2. **Projekt na żywo** (zrobione): lista pokazuje prawdziwy model, półfabrykat i
   narzędzia (biblioteka warsztatu), a szczegóły pokazują ich dane. Zaznaczanie jest
   wspólne dla listy i widoku 3D.
   - Projekt = jeden Job FreeCAD CAM w dokumencie. Powstaje automatycznie przy
     imporcie modelu, a kolejne importy dochodzą do tego samego Joba.
   - Półfabrykat = obrys modelu + naddatki. Domyślnie 1 mm na boki i na górę, 0 mm na
     dół, bo detal leży na stole. Naddatki edytuje się w Details polami z jednostką
     (wpisane „0.5 in” zamienia się na 12.70 mm). Każda zmiana to jeden krok Undo.
   - Domyślny frez 5 mm, który FreeCAD dodaje do nowego Joba, jest usuwany. Narzędzi
     używanych przez operację nie da się usunąć.
   - Na nowym profilu tłumacz sam ustawia `CamAssets` (kształty narzędzi), tak jak robi
     to workbench CAM przy starcie.

### Biblioteka narzędzi (poza FreeCADem)

To samo fizyczne narzędzie występuje w warsztacie kilka razy pod tym samym numerem T:
osobno dla aluminium, RVS i stali (inne obroty i posuwy) albo z inną płytką (T14: R1,
R2, R5). W jednym programie i tak używa się tylko jednego wariantu.

- Biblioteka to plik JSON w naszym formacie (`model/library.py`), domyślnie
  `Resources/library/tools.json`. Inny plik, np. na dysku sieciowym, wskazuje parametr
  `ToolLibraryFile` albo przycisk „Open other library...”. FreeCAD nic o niej nie wie.
- Każdy wariant ma własne **ID** (np. `t40-rvs-nx-boor-6.8mm-rvs`), a numer T może się
  powtarzać.
- W projekcie (Job FreeCADa) jeden numer T to jeden ToolController, a numer narzędzia
  FreeCADa to zawsze numer T. ToolController pamięta ID i materiał wariantu
  (`AvangardeToolId`, `AvangardeMaterial`).
- Wybór innego wariantu numeru, który jest już w projekcie, to **zamiana** w tym samym
  ToolControllerze. Program najpierw pyta, a operacje zostają podpięte i dostają nowe
  obroty i posuwy.
- Dodanie i zamiana narzędzia nie są krokiem cofania (pułapka FreeCADa, patrz Contour
  tooling); narzędzie usuwa się przyciskiem „Remove from project”.
- Obroty i posuwy wpisuje tłumacz wprost do ToolControllera. Wartości z jednostką
  tworzy `_quantity()` z tekstu i sprawdza w obie strony, bo
  `Quantity(1250, Unit("mm/min"))` FreeCAD czyta jako 1250 **mm/s**.
- Biblioteka powstała z tabeli narzędzi warsztatu: 276 wariantów (frezy, fazowniki, wiertła,
  frezy do gwintów). Importer leży poza repozytorium. Niezgodności w danych (np. nazwa „…RVS”
  przy materiale Staal) zostają jak w tabeli; wartości są zaokrąglone do 6 miejsc.
- Frez do gwintów: geometria z tabeli warsztatu (promień, promień chwytu i szyi, długość zębów,
  długość całkowita, zasięg „L” od czubka do chwytu = `NeckLength` FreeCADa, skok).
  Kąt profilu nie jest zapisany w tabeli: 55° dla gwintów G (BSP), poza tym 60°.
  ThreadMill FreeCADa nie ma skoku ani długości zębów: skok trzyma dodatkowa
  właściwość `Pitch` bita, długość zębów FreeCAD zapisuje sam jako tekst
  (`CuttingEdgeHeight`, odczyt w `_tool_from_controller`). `Crest` zostaje domyślny
  FreeCADa (0.1 mm), bo tabela go nie podaje.
3. **Pierwsza operacja od początku do końca** (zrobione): mocowania i Snap-0-Point,
   Extract boundary edges (szkic ze ściany), Contour tooling (Engrave po szkicu, T21,
   Z-Depth ujemny). Ścieżka leży na detalu w 3D, Z-Depth zmienia się w Details na
   żywo z undo, a dwuklik w 3D wraca do naszego panelu. Testy: model, tłumacz,
   GUI (`tests_gui/test_setups.py`).
   - 3a (zrobione): szkic widoczny (zielony, gruby, czerwony po zaznaczeniu),
     klikanie linii z pierwszeństwem szkicu nad modelem, Contour tooling tylko po
     zaznaczonych liniach w kolejności kliknięć (`tests_gui/test_lines.py`).
   - 3b (zrobione): zaznaczanie jak w Blenderze (Alt+klik pętla, Shift+klik wiele
     linii, Ctrl+klik najkrótsza ścieżka).
   - 3c (zrobione): strzałka kierunku w połowie każdej zaznaczonej linii, klik w
     strzałkę odwraca łańcuch, Contour tooling jedzie zgodnie ze strzałkami.
4. **Kolejne operacje** według częstości użycia.
   - 4a (zrobione): wiercenie cyklem 205: okręgi szkicu w kolejności kliknięć, program
     `.H` jak programy warsztatu, okno Drilling i Details (`tests_gui/test_drilling.py`); otwory
     klikane w modelu 3D z głębokością z modelu i podpowiedzią wiertła
     (`tests_gui/test_model_drilling.py`).
   - 4b (zrobione): frezowanie gwintów jak w programach warsztatu (helisa z RR, identyczne przejścia,
     tytuł `Thread Milling`), okno Thread milling i Details, otwory ze szkicu i z modelu
     (`tests_gui/test_thread_milling.py`).
   - 4c (zrobione): Adaptive clearing: model, tłumacz i program, okno, wstążka, Details i
     Edit... (`tests_gui/test_adaptive.py`).
   - 4d (zrobione): Facing samej góry modelu po całym stocku, zygzak / jednostronnie, kierunek
     (`tests/test_facing.py`, `tests_gui/test_facing.py`); ściany i stopnie w silniku na później.
   - 4e (zrobione, część 1): Slot milling slobgatów prostych klikanych w modelu: rampa wahadłowa,
     przejścia zgrubne, ściany z RL/RR (`tests/test_slot.py`, `tests_gui/test_slot.py`); szkic i
     slobgat po łuku później.
5. **Program NC**: postprocesor pod konkretną maszynę i sterownik, eksport z menu File.
   - 5a (zrobione): Heidenhain TNC 620 Klartext `.H` jak programy warsztatu, ruchy L/CC/C,
     jeden program z presetem na mocowanie.
   - 5b (zrobione, tymczasowo): CAM > Simulate, symulator OpenGL FreeCADa dla
     aktywnego mocowania.
   - 5c (zrobione): kompensacja narzędzia w Contour tooling (Off / RL / RR) i w
     postprocesorze; sposób dojazdu (łuk z promieniem, domyślnie zjazd 0,5 mm obok
     konturu, albo prosto w dół), z kompensacją i bez.
6. (opcjonalnie) **Natywny silnik** obok FreeCADa.

## Testy

- model i postprocesor: zwykły `python3 -m unittest` (bez FreeCADa);
- engine: `FreeCADCmd` + runner `unittest`;
- GUI (`test_layout.py`, `test_project.py`, `test_setups.py`): zagnieżdżony X (`Xephyr :5`), osobny `FREECAD_USER_HOME` w katalogu
  tymczasowym, skrypt testowy jako argument FreeCADa i zrzuty ekranu.
  Tryb `QT_QPA_PLATFORM=offscreen` zawiesza się, bo nie ma OpenGL.
- Zapamiętane wartości okien (ostatnie narzędzie, głębokość, kompensacja, przejścia,
  wiercenie, foldery) to parametry o nazwach `Last…`; każdy test GUI zaczyna od
  `avangardecam.forget_last_values()`, więc wynik nie zależy od profilu. Nowa
  zapamiętywana wartość też musi mieć nazwę `Last…`.
- Testowy model: `demo_bridge.step`.

## Ciemny motyw systemu pod jasnym motywem FreeCADa (2026-11-18)

FreeCAD z Flatpaka bierze paletę z systemu (Pop dark, `prefer-dark`), a motyw „FreeCAD Light”
przemalowuje tylko widżety, które zna. Panel Details pod listą projektu (QScrollArea) malował
viewport i widok tłem z palety, czyli ciemnym, a tekst miał czarny z motywu. Podpisy w Details
i podpisy grup na wstążce miały `palette(mid)`: ciemny na ciemnym systemie, prawie biały na jasnym.
Teraz viewport i widok Details są przezroczyste (tło doku jak lista), a podpisy mają stały szary
#808080, czytelny na jasnym i ciemnym tle. Test: `tests_gui/test_dark_system.py` (profil z
`test_dark_system.user.cfg`, ciemna paleta Qt podana w teście).

Czarna aktywna zakładka (CAD/CAM i zakładka dokumentu) na zrzutach z testowego profilu to nie błąd
programu: motyw „FreeCAD Light” bierze kolor aktywnej zakładki z koloru tła widoku 3D
(`@ActiveTabBackgroundColor` = `@3DViewBackgroundRefColor` = `@BackgroundColor`, czyli
`View/BackgroundColor`). Profil bez tego parametru daje czarny; prawdziwy profil FreeCAD Light ma
jasny (#F7F7F7). Dlatego `test_dark_system.user.cfg` ma też grupę `View` z tym kolorem.

## Podpisy dużych przycisków wstążki w dwóch linijkach (2026-11-18)

Zakładka CAM w jednej linijce potrzebowała 2191 px, ekran 1920 ma 1912: Qt ściskał duże przyciski
i ucinał podpisy („Nex…tup”, „Snap…oint”, „Ex…NC”). Teraz podpis dużego przycisku jest w dwóch
linijkach jak we wstążce Office (`ribbon.two_lines`): łamany na spacji, która daje najkrótszą dłuższą
linijkę; jedno słowo dostaje pustą drugą linijkę, żeby podpisy stały równo. CAM potrzebuje 1876 px.
Test: `test_layout.py` (żaden przycisk węższy niż jego podpis przy 1920 px).
