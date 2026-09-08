# ImgGen2

## 생성 버튼은 누구나 누릅니다. **팔리고, 선택되고, 납품되는 이미지는 다릅니다.**

[![Release](https://img.shields.io/github/v/release/HeiTuz/ImgGen2?style=flat-square)](https://github.com/HeiTuz/ImgGen2/releases/latest)
[![CI](https://img.shields.io/github/actions/workflow/status/HeiTuz/ImgGen2/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/HeiTuz/ImgGen2/actions)
[![License: MIT](https://img.shields.io/badge/license-MIT-black?style=flat-square)](LICENSE)

**ImgGen2**는 ChatGPT 구독을 실제 이미지 제작 파이프라인으로 바꾸는 스킬입니다.

제품 사진 한 장부터 캠페인 비주얼 100장까지, 생성하고 끝내지 않습니다. 레퍼런스를 지키고, 후보를 비교하고, 실패한 컷만 다시 만들고, **바로 쓸 수 있는 최종본만 남깁니다.**

## 이런 이미지를 만듭니다

### 한 장이면, 한 장부터 제대로

텍스트로 새 이미지를 만들고, 레퍼런스 이미지를 원하는 장면으로 바꿉니다.

제품 디테일, 인물의 정체성, 반드시 유지해야 할 요소를 먼저 잠급니다. 분위기는 과감하게 바꿔도 결과의 주인공은 망가지지 않습니다.

### 여러 장이면, 하나의 캠페인처럼

제품컷, 룩북, 카드뉴스, 광고 소재는 한 장씩 운에 맡기는 순간 톤도 품질도 흔들립니다.

ImgGen2는 같은 목표를 공유하는 이미지들을 한 세트로 관리해, **첫 컷부터 마지막 컷까지 한 브랜드처럼 보이게** 만듭니다.

### 제품은 지키고, 판매력은 끌어올립니다

제품 사진은 예쁘기만 해서는 안 됩니다. 고객이 받을 바로 그 제품이어야 합니다.

앞·뒤·소재·디테일을 빠뜨리지 않고 후보 세트를 비교합니다. 최종 폴더에는 **선택된 판매용 컷만 남습니다.**

### 실패한 컷이 최종본에 숨어들지 못합니다

그럴듯하지만 틀린 이미지를 조용히 섞어두지 않습니다.

완성도, 제품 충실도, 구도, 일관성을 기준으로 결과를 점검하고 실패한 부분만 다시 만듭니다. 좋은 컷까지 갈아엎는 재생성 낭비를 줄입니다.

## 이런 작업이라면 바로 체감합니다

- ChatGPT로 이미지 만들지만 결과 관리까지 제대로 하고 싶은 사람
- 제품 사진·패션 비주얼·브랜드 콘텐츠를 여러 장 제작하는 사람
- 레퍼런스를 쓰면서도 핵심 요소가 무너지는 게 싫은 사람
- 생성 이미지와 최종 납품 이미지를 깔끔하게 분리하고 싶은 사람
- “만들었다”가 아니라 “검수해서 쓸 수 있다”를 원하는 사람

## 30초면 제작 환경이 붙습니다

**한 줄이면 공식 Codex CLI + ImgGen2 + MPW가 같이 붙습니다.** 설치기가 이 컴퓨터의 에이전트 환경(Hermes·Claude Code·Codex)을 자동 감지해 맞는 위치를 고릅니다.

```bash
npx --yes --package github:HeiTuz/ImgGen2 imggen-imggen2
# 또는
bunx --package github:HeiTuz/ImgGen2 imggen-imggen2
```

### 자동 감지와 호스트 선택

- **감지 신호**: `~/.hermes`, `~/.claude`, `~/.codex` 같은 잘 알려진 스킬 디렉터리·CLI 설치 흔적만 봅니다. 비밀값이나 설정 파일 내용은 읽지 않습니다.
- **대화형 터미널**: 감지된 호스트를 보여주고 하나를 선택·확인합니다.
- **CI·비대화형**: 절대 묻지 않습니다. 1개 감지 → 그대로 설치. 여러 개 감지 → Hermes 우선, Hermes가 없으면 `hermes > claude > codex` 우선순위의 첫 감지 대상. 0개 감지 → Hermes 위치에 설치(문서화된 기본값).
- **ImgGen2와 MPW는 항상 같은 호스트에** 나란히 설치됩니다 — ImgGen2는 Hermes에, MPW는 다른 곳에 가는 어긋남이 없습니다.
- Hermes가 기본·선호 환경입니다. Claude Code·Codex 설치는 규칙 본문이 동일한 채 호스트 통합 표면(발동·도구 명칭·frontmatter)만 마이그레이션된 변형을 받습니다 — 구조와 근거는 [agents/README.md](agents/README.md).

| 호스트 | ImgGen2 | MPW |
|---|---|---|
| Hermes (기본·권장) | `~/.hermes/skills/ImgGen2` | `~/.hermes/skills/prompt-writing/MPW` |
| Claude Code | `~/.claude/skills/ImgGen2` | `~/.claude/skills/MPW` |
| Codex | `~/.codex/skills/ImgGen2` | `~/.codex/skills/MPW` |

명시 디렉터리 지정(`--target <dir>`, `--mpw-target <dir>`)은 항상 자동 감지를 이깁니다.

```bash
npx --yes --package github:HeiTuz/ImgGen2 imggen-imggen2 -- \
  --target "$HOME/.hermes/skills/ImgGen2" \
  --mpw-target "$HOME/.hermes/skills/prompt-writing/MPW"
```

### Codex CLI 경로

설치기는 운영체제에 맞춰 공식 Codex 설치 경로를 사용합니다.

| 환경 | Codex 기본 경로 | `imggen` 명령 |
| --- | --- | --- |
| macOS / Linux | `~/.local/bin/codex` | `~/.local/bin/imggen` |
| Windows | `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe` | `%LOCALAPPDATA%\HeiTuz\bin\imggen.cmd` + `imggen.ps1` |

macOS/Linux는 `~/.profile`과 `~/.zprofile`에 `~/.local/bin`을 추가합니다. Windows 설치기는 구형 HeiTuz PATH/확장자 없는 launcher를 제거하고 `%LOCALAPPDATA%\HeiTuz\bin`을 사용자 PATH 맨 앞에 등록합니다. 설치 뒤 새 Terminal을 열면 바로 `imggen update`가 됩니다. Windows에서 파일을 열 앱 선택 창이 뜨는 구형 설치는 아래 명령으로 launcher를 직접 실행한 뒤 설치기를 다시 적용하세요.

```powershell
& "$env:LOCALAPPDATA\HeiTuz\bin\imggen.cmd" update
```

### Windows 구형 임시 경로 설치 복구

`imggen status` 또는 `imggen update`가 삭제된 `imggen-unified-*` 모듈을 가리키며 `MODULE_NOT_FOUND`를 내거나, `%APPDATA%\HeiTuz\installation.json`의 `imggen2_target`이 Temp 아래 `imggenimggen2-install-*`에 남아 있다면 현재 설치기를 다시 등록합니다. 이 명령은 다른 스킬을 삭제하지 않고 Hermes의 정식 ImgGen2/MPW 디렉터리와 전역 launcher/manifest만 교체합니다.

```powershell
npx --yes --package github:HeiTuz/ImgGen2 imggen-imggen2 -- --agent hermes --force --register
```

설치기는 Git Bash가 먼저 찾는 구형 `~/.local/bin/imggen`, obsolete extensionless launcher, 오래된 HeiTuz PATH marker를 검사해 임시 또는 사라진 대상을 가리키는 항목만 복구합니다. 새 터미널을 연 뒤 세 셸에서 같은 안정 updater를 찾는지 확인합니다.

```bash
# Git Bash / MSYS
command -v imggen
imggen status
```

```cmd
where imggen
imggen status
```

```powershell
Get-Command imggen
imggen status
```

`status`는 선택된 launcher, manifest 경로/버전, 각 대상 존재 여부와 설치 버전, Hermes 활성 대상 일치 여부를 표시합니다. 손상이 남아 있으면 비zero로 종료하면서 복사해 실행할 수 있는 repair 명령을 출력합니다.
## Vision-QC 설정

기본 모드 `auto`는 모든 생성물을 무조건 검수하지 않습니다. 레퍼런스 이미지가 있거나, 기존 이미지를 편집하거나, 제품사진을 보정하거나, 광고 레이아웃을 만들거나, 사용자가 검수·비교를 명시한 경우에만 현재 호스트의 기본 Vision 모델을 사용합니다. 텍스트만으로 단순 이미지를 만드는 경우에는 파일 유효성만 확인하고 Vision-QC와 재생성 루프를 생략합니다. Hermes에서는 필요한 경우 `vision_analyze`가 `auxiliary.vision` 설정을 따라 실행됩니다.

온라인 설치는 QC용 임시 썸네일 처리에 필요한 Pillow를 현재 사용자 Python 환경에 설치 시도합니다. PEP 668 externally-managed Python처럼 자동 설치가 거부되는 환경에서는 경고 후 설치를 계속 진행합니다. `--offline` 설치는 네트워크 접근 없이 파일만 복사하고, 전역 launcher/manifest 등록은 `--register`를 명시할 때만 수행합니다.

```bash
# 기본값이며 별도 지정할 필요 없음
npx --yes --package github:HeiTuz/ImgGen2 imggen-imggen2 -- --vision-qc auto

# QC를 완전히 끌 때만 명시
npx --yes --package github:HeiTuz/ImgGen2 imggen-imggen2 -- --vision-qc off
```

`auto`는 작업 위험도에 따라 Vision-QC 필요 여부를 결정하고, 필요할 때만 현재 호스트의 기본 Vision tool을 사용합니다. `off`는 시각 검수를 전부 끄지만 파일 존재·형식·크기·충돌 같은 로컬 무결성 검사는 계속 수행합니다.

대화형·비대화형 설치와 업데이트 모두 명시 옵션이 없으면 `auto`를 사용합니다. 모델·provider 선택은 ImgGen2가 아니라 호스트의 Vision 설정이 소유합니다.

## Windows 및 다른 OS 경로

Windows에서는 `C:\\...`, UNC 공유 경로(`\\\\server\\share\\...`), 공백·Unicode 경로, `file:///C:/...`를 지원합니다. `/mnt/c/...`는 의미가 확정되므로 `C:\\...`로 변환할 수 있습니다. 긴 절대경로는 Windows extended-length 형식으로 정규화합니다.

반대로 `/Users/...`·`/Volumes/...`는 macOS 머신의 로컬 경로이므로 Windows의 `C:\\Users\\...`로 추측 변환하지 않습니다. `/home/...` 같은 Linux 경로와 다른 머신의 Windows 경로도 마찬가지입니다. 이 경우 파일을 현재 컴퓨터로 복사·재첨부하거나, 실제 Windows 로컬 경로 또는 UNC 공유 경로를 다시 지정해야 합니다. `file://` URI에 사용자명·비밀번호를 넣는 것도 거부합니다.

## 공유폴더 제품사진 일괄보정

`\\Dint\00.딘트공유\상품촬영\2026SS\상품코드` 같은 공유폴더 경로 하나만 주면, 패키지에 포함된 `scripts/folder_batch_prepare.py`가 원본을 읽기 전용으로 유지한 채 인벤토리 → 파일명 역할 매핑(`f1` 앞면, `b1` 뒷면, `fN`/`bN` 변형, `cN` 컬러 앞면, `d1_원단` 같은 `dN` 디테일, `sN` 합성 소스) → Vision 핸드오프 → 기본 보정·QC 계약 → 출력 계획까지 검증된 계약 파일로 만들어 줍니다. 알 수 없는 파일명이나 충돌은 즉시 실패로 보고하고, `Thumbs.db` 같은 일반 아티팩트는 무시하며, 결과물은 원본 폴더 안의 새 `AI_RESULT_타임스탬프/` 하위 폴더에만 게시됩니다(기존 파일 덮어쓰기 없음).

```bash
python scripts/folder_batch_prepare.py \
  --input-dir "//Dint/00.딘트공유/상품촬영/2026SS/상품코드" \
  --mode apparel-product-correction \
  --publish-subfolder auto \
  --dry-run
```

자세한 절차와 완료 JSON 예시는 [`examples/dint-shared-folder-apparel-batch.md`](examples/dint-shared-folder-apparel-batch.md)에 있습니다.

## 대량 아이데이션·레퍼런스 보드

“서브컬처·독립잡지 스타일 고양이 레퍼런스 100장”처럼 텍스트 아이디어를 대량으로 변주하는 작업은 Vision QC를 돌리지 않습니다. MPW가 구도·시점·조명·팔레트·재질·공간 리듬을 분산한 프롬프트를 먼저 만들고 ImgGen2가 생성만 수행합니다.

```bash
python3 examples/batch_100_variations.py \
  --prompt "서브컬처 독립잡지 같은 검은 고양이 초상" \
  --style "anti-mainstream editorial, dry and strange" \
  --count 100 \
  --output-root ./indie-editorial-cats \
  --execute
```

성공 후 출력 폴더에는 PNG만 남습니다. manifest·ledger·summary·임시 요청은 숨김 workspace에서 제거되며, 실패나 중단 때만 재개를 위해 workspace를 보존합니다. 단순 텍스트 한 장도 MPW가 설치돼 있으면 자동 보강되고 `--mpw off`로 끌 수 있습니다.

### 포함된 예제

| 파일 | 기본 사례 | 수량 |
| --- | --- | ---: |
| `examples/indie_editorial_100.py` | 서브컬처·독립잡지 레퍼런스 | 100 |
| `examples/fashion_moodboard_80.py` | 패션 컬렉션 무드보드 | 80 |
| `examples/album_cover_directions_40.py` | 가상 앨범커버 방향 탐색 | 40 |
| `examples/character_silhouettes_64.py` | 캐릭터 실루엣 탐색 | 64 |
| `examples/package_concepts_50.py` | 텍스트 없는 패키지 콘셉트 | 50 |
| `examples/interior_directions_48.py` | 소형 문화공간·인테리어 방향 | 48 |
| `examples/product_hero_shots_24.py` | 상세페이지 첫 컷용 클린 제품 히어로 | 24 |
| `examples/marketplace_thumbnails_32.py` | 오픈마켓 그리드용 썸네일 방향 | 32 |
| `examples/detail_closeups_20.py` | 소재·봉제·마감 디테일 클로즈업 | 20 |
| `examples/color_variant_lineup_18.py` | 옵션 선택용 컬러 변형 라인업 | 18 |
| `examples/lifestyle_product_scenes_24.py` | 사용 맥락 라이프스타일 연출 컷 | 24 |
| `examples/seasonal_campaign_banners_16.py` | 카피 여백 확보 시즌 캠페인 배너 | 16 |
| `examples/bundle_set_compositions_16.py` | 번들·기프트 세트 구성 컷 | 16 |
| `examples/beauty_cosmetics_shots_24.py` | 뷰티·코스메틱 텍스처 연출 | 24 |
| `examples/food_beverage_shots_24.py` | 식음료 판매용 식욕 자극 컷 | 24 |
| `examples/home_living_scenes_24.py` | 홈·리빙 침실/공간 스테이징 | 24 |
| `examples/apparel_catalog_looks_28.py` | 의류 카탈로그·룩북 룩 탐색 | 28 |
| `examples/single_mpw_enhanced.py` | 단일 텍스트 요청 MPW 보강 | 1 |

각 예제는 인자 없이 실행하면 자기 기본값으로 dry-run합니다. `--prompt`, `--style`, `--count`, `--output-root`로 필요한 축만 덮어쓰고, 실제 생성할 때만 `--execute`를 붙입니다. 실행 로직은 `preset_runner.py`와 본체에만 있어 사례 파일을 복사해도 유지보수 코드가 늘어나지 않습니다.

### 쇼핑몰 운영자용 예제 실행

쇼핑몰 예제는 전부 **텍스트 전용 아이데이션 프리셋**입니다. 방향을 대량으로 탐색하는 용도이며, 레퍼런스 이미지를 넣어 실제 제품을 충실하게 보정하는 작업(`--image`)은 이 프리셋이 아니라 본체 제품사진 흐름을 사용해야 합니다.

```bash
# 기본값 그대로 dry-run으로 계획만 확인
python3 examples/product_hero_shots_24.py

# 프롬프트만 우리 상품으로 바꿔 실제 생성
python3 examples/marketplace_thumbnails_32.py \
  --prompt "핸드메이드 소이캔들 3종 썸네일 컷" \
  --execute

# 수량과 출력 폴더까지 덮어쓰기
python3 examples/seasonal_campaign_banners_16.py \
  --prompt "설 선물세트 프로모션 배너 비주얼" \
  --count 8 \
  --output-root ./seollal-banners \
  --execute
```

Windows batch ledger가 OneDrive·SMB·백신의 짧은 파일 잠금과 충돌해 `WinError 5` 또는 `WinError 32`를 내면 atomic replace를 제한적으로 재시도합니다. 출력 경로의 symlink뿐 아니라 junction/reparse point도 거부합니다. `npm test`와 install smoke는 Windows/macOS/Linux CI에서 각각 실행됩니다.

## 업데이트도 한 줄이면 끝

```bash
imggen update
```

이 명령은 **ImgGen2와 MPW를 함께 갱신**합니다. Codex까지 강제로 갱신하려면:

```bash
imggen update --codex
```

무엇을 실행할지만 보고 싶다면:

```bash
imggen update --dry-run
```

특정 폴더에 ImgGen2만 따로 설치하는 기존 경로도 남아 있습니다.

```bash
npx --yes --package github:HeiTuz/ImgGen2 imggen-imggen2 -- --target "$HOME/.hermes/skills/ImgGen2" --skip-mpw --skip-codex
```

## Grok은 명시했을 때만

기본 이미지 생성은 계속 Codex 구독 경로를 사용합니다. Grok은 Hermes에 **xAI OAuth가 연결되어 있고**, 요청에 `Grok`, `그록`, 또는 `xAI로 생성`이 명시된 경우에만 선택됩니다.

```text
Grok으로 이 콘셉트 이미지를 20장 만들어줘.
```

20장은 한꺼번에 폭격하지 않습니다. 먼저 1장으로 생성·품질을 확인한 뒤 3개 작업으로 시작해 최대 5개까지 제한적으로 처리하고, 나머지는 큐에 남깁니다. 실패한 장만 다시 생성합니다.

OAuth가 없거나 현재 Hermes 세션에 xAI 이미지 도구가 없으면 Grok 경로는 비활성으로 끝납니다. API 키만으로 대신 실행하거나, Codex·Higgsfield로 조용히 바꾸지 않습니다. 자세한 계약은 [`references/grok-oauth-explicit-routing.md`](references/grok-oauth-explicit-routing.md)에 있습니다.

## 말하듯 요청하면 됩니다

```text
이 제품 사진을 정사각형 상세페이지 컷으로 정리해줘.
제품의 색·실루엣·소재·봉제 디테일은 바꾸지 말고, 배경만 자연스럽게 확장해.
```

```text
이 인물을 유지한 채, 비 오는 도쿄 골목의 패션 에디토리얼 한 컷으로 만들어줘.
```

```text
이 브랜드의 여름 캠페인용 이미지를 6장 만들어줘.
모든 컷이 같은 세계관과 색감으로 보이게 해.
```

```text
이 레퍼런스들을 합쳐 프리미엄 향수 광고 비주얼을 만들어줘.
제품 병의 형태와 라벨은 정확히 유지해.
```

## 아이디어는 과감하게. 최종본은 냉정하게.

좋은 이미지는 운 좋게 나온 한 장이 아닙니다.

**원하는 장면을 만들고, 기준으로 고르고, 실제로 돈을 벌고 브랜드를 세울 컷만 남기세요.**

ImgGen2가 생성부터 최종 선별까지 밀어붙입니다.

병렬 Codex 워커 실행 구조의 출발점은 [gongnyang/codex-fleet](https://github.com/gongnyang/codex-fleet)입니다. 원본과의 차이, 배치 재개 보호, 대량 작업 메모리 사용, 오류 시 작업 투입 중단의 구현 근거는 [배치 안정성·확장성 검토](references/reliability-and-scaling.md)에 있습니다.

GPT-6 Astra용 작업 지침은 간결한 진입 문서와 모드별 절차로 나뉩니다. 배치 결과의 `completion_state`·`next_action`, PNG 구조·해시 검증, 검수 보고서에 묶인 재개, 전체 컷을 확인하는 게시 절차로 후속 행동을 정합니다. 설계 근거와 검증 한계는 [Astra 실행 설계](references/astra-orchestration.md)를 참고하세요.

## License

MIT © HeiTuz
