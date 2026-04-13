# Short-Form Pipeline 사용 가이드

## 목차

1. [시작하기](#시작하기)
2. [프로젝트 생성](#프로젝트-생성)
3. [JSON 스크립트 형식](#json-스크립트-형식)
4. [파이프라인 단계](#파이프라인-단계)
5. [리뷰 및 승인](#리뷰-및-승인)
6. [모델 설정](#모델-설정)
7. [외부 API 프로바이더 설정](#외부-api-프로바이더-설정)
8. [생성된 파일 위치](#생성된-파일-위치)
9. [제한 사항](#제한-사항)

---

## 시작하기

### 접속 URL

- **Studio Web UI**: `http://localhost:5174` (로컬) / `http://<LAN_IP>:5174` (외부)
- **API**: `http://localhost:8000` (내부 prefix: `/api/creator`)

### 서비스 실행

```bash
cd short-form-studio
docker compose up -d
```

필수 서비스: `postgres`, `redis`, `api`, `worker`, `studio-web`, `ollama`

선택 서비스 (GPU 필요):
- `stable-diffusion` — 이미지 생성 (6GB+ VRAM)
- `tts-qwen3` — TTS 음성 생성
- `stt-whisper` — 자막 생성 (Whisper large-v3)

> ⚠️ GPU(GTX 1660 SUPER 6GB)에서는 GPU 서비스를 동시에 실행할 수 없습니다. 필요한 서비스만 선택적으로 실행하세요.

---

## 프로젝트 생성

Studio Web UI에서 **"Create New Project"** 버튼을 클릭하면 두 가지 탭이 제공됩니다:

> 현재 제품 UI에서 지원하는 시작 방식은 **Idea** 와 **JSON** 두 가지입니다.
> `URL`, `Markdown` source는 레거시/내부 계약에는 남아 있을 수 있지만, 현재 사용자 플로우에서는 지원하지 않습니다.

### 탭 1: Start from Idea

아이디어에서 AI가 자동으로 스크립트를 생성합니다.

| 필드 | 필수 | 설명 |
|------|------|------|
| **Title** | ✅ | 프로젝트 제목 |
| **Idea Brief** | ✅ | 영상 아이디어 설명 (자유 형식) |
| **Target Duration** | - | 목표 길이 (초, 기본값 60, 범위 10~180) |
| **Content Goal** | - | 콘텐츠 목표 (예: educational, entertainment) |

→ "Create Project" 클릭 시: 프로젝트 생성 → AI가 스크립트 자동 생성 → 프로젝트 페이지로 이동

### 탭 2: Start from JSON

ChatGPT 등에서 생성한 JSON 스크립트를 입력합니다.

| 필드 | 필수 | 설명 |
|------|------|------|
| **Title** | - | 프로젝트 제목 (미입력 시 "Untitled") |
| **JSON Script** | ✅ | JSON 형식의 씬 스크립트 (직접 입력 또는 파일 업로드) |

→ `.json` 또는 `.txt` 파일 업로드도 가능합니다.

#### JSON 스크립트 형식

```json
{
  "scenes": [
    {
      "type": "hook",
      "text": "여러분, AI가 60초 만에 영상을 만들어준다면 믿으시겠어요?",
      "image_prompt": "A futuristic holographic AI interface creating video content...",
      "speaker": "host",
      "mood": "exciting",
      "composition": "medium shot, centered",
      "style_tags": ["cinematic", "sci-fi"]
    }
  ]
}
```

| 필드 | 필수 | 설명 |
|------|------|------|
| `type` | ✅ | 씬 유형 (hook, body, cta 등) |
| `text` | ✅ | 나레이션/스크립트 텍스트 |
| `image_prompt` | - | 이미지 생성 프롬프트 (비주얼 플랜에서 우선 사용) |
| `speaker` | - | 화자 (예: host, narrator) |
| `mood` | - | 분위기 (예: exciting, calm) |
| `composition` | - | 구도 (예: close-up, wide shot) |
| `style_tags` | - | 스타일 태그 목록 |
| `display_text` | - | 화면 표시 텍스트 (자막 오버라이드) |
| `duration` | - | 씬 길이 (초) |

### 공통 설정

- **Model Defaults**: 스크립트/이미지 생성에 사용할 모델 선택
- **Style Preset**: `default`, `cinematic`, `dynamic`, `minimal` 중 선택

---

## JSON 스크립트 형식

> JSON 스크립트 형식에 대한 자세한 내용은 위의 [탭 2: Start from JSON](#탭-2-start-from-json) 섹션을 참고하세요.

---

## 파이프라인 단계

프로젝트 생성 후 자동으로 파이프라인이 진행됩니다:

```
IDEA_READY → SCRIPT_GENERATING → SCRIPT_REVIEW
    → VISUAL_PLAN_GENERATING → VISUAL_PLAN_REVIEW
    → VISUAL_ASSET_GENERATING → VISUAL_ASSET_REVIEW
    → AUDIO_GENERATING → SUBTITLE_GENERATING
    → RENDER_GENERATING → FINAL_REVIEW
```

| 단계 | 설명 | 사용 모델 |
|------|------|-----------|
| **SCRIPT_GENERATING** | 아이디어에서 스크립트 생성 (JSON 입력 시 건너뜀) | Ollama (qwen3:4b) |
| **SCRIPT_REVIEW** | 생성된 스크립트 검토 및 승인 | - |
| **VISUAL_PLAN_GENERATING** | 각 섹션별 비주얼 플랜(프롬프트) 생성 | Ollama (qwen3:4b) |
| **VISUAL_PLAN_REVIEW** | 비주얼 플랜 검토 및 승인 | - |
| **VISUAL_ASSET_GENERATING** | 이미지 생성 | Stable Diffusion (로컬) |
| **VISUAL_ASSET_REVIEW** | 생성된 이미지 검토 및 승인 | - |
| **AUDIO_GENERATING** | 스크립트 텍스트 → 음성(TTS) 변환 | Qwen TTS (로컬) |
| **SUBTITLE_GENERATING** | 음성 → 자막(SRT) 생성 | Whisper large-v3 (로컬) |
| **RENDER_GENERATING** | 이미지 + 음성 + 자막 → 최종 영상 렌더링 | FFmpeg |
| **FINAL_REVIEW** | 최종 영상 검토 | - |

---

## 리뷰 및 승인

각 `_REVIEW` 단계에서 **Approve** 또는 **Reject** 할 수 있습니다.

### Project Page

프로젝트 페이지에서 현재 진행 단계와 리뷰 상태를 확인할 수 있습니다.
- **Approve**: 다음 단계로 자동 진행
- **Reject**: 해당 단계를 재생성

### Review Page

`FINAL_REVIEW` 단계에 도달하면 **"Open Review Page"** 링크가 표시됩니다.
리뷰 페이지에서는 모든 생성물을 한 눈에 확인할 수 있습니다:
- 스크립트 전문
- 비주얼 플랜
- 생성된 이미지 (섹션별)
- 오디오 재생
- 자막 (SRT)
- 최종 렌더링 영상 재생

---

## 모델 설정

### 현재 기본 모델 (로컬)

| 카테고리 | 모델 | 설명 |
|----------|------|------|
| **LLM (스크립트/플랜)** | `qwen3:4b` (Ollama) | 스크립트 생성 및 비주얼 플랜 생성 |
| **이미지** | Stable Diffusion (로컬) | SD WebUI를 통한 이미지 생성 |
| **TTS** | Qwen TTS (로컬) | 텍스트 → 음성 변환 |
| **STT** | Whisper large-v3 (로컬) | 음성 → 자막 변환 |

### 모델 선택

프로젝트 생성 시 **"Model Defaults"** 섹션에서 카테고리별 모델을 선택할 수 있습니다.
로컬 모델과 외부 API 프로바이더 모두 지원합니다. 자세한 설정은 [외부 API 프로바이더 설정](#외부-api-프로바이더-설정) 섹션을 참고하세요.

## 외부 API 프로바이더 설정

로컬 모델 외에 외부 API를 사용하여 더 높은 품질의 결과물을 생성할 수 있습니다.

### 지원 프로바이더

| 카테고리 | 프로바이더 | 모델 | 환경 변수 |
|----------|-----------|------|-----------|
| **LLM** | OpenAI | GPT-4o Mini | `OPENAI_API_KEY` |
| **LLM** | Anthropic | Claude Sonnet | `ANTHROPIC_API_KEY` |
| **LLM** | Google | Gemini 2.0 Flash | `GOOGLE_API_KEY` |
| **이미지** | OpenAI | DALL-E 3 | `OPENAI_API_KEY` |
| **이미지** | Stability AI | SD3 Medium | `STABILITY_API_KEY` |
| **이미지** | Google | Imagen 3 | `GOOGLE_API_KEY` |
| **TTS** | ElevenLabs | Multilingual v2 | `ELEVENLABS_API_KEY` |
| **TTS** | OpenAI | TTS-1 | `OPENAI_API_KEY` |

### API 키 설정 방법

현재 Settings 페이지는 **API 키 편집/저장 기능이 없는 읽기 전용 상태 페이지**입니다.
`/settings`에서 각 프로바이더 키의 설정 여부만 확인할 수 있으며, 실제 키 값은 서버 환경 변수에서 관리합니다.

#### .env 파일 편집

`.env` 파일에 API 키를 추가합니다:

```bash
OPENAI_API_KEY=sk-your-openai-key
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key
GOOGLE_API_KEY=your-google-api-key
STABILITY_API_KEY=sk-your-stability-key
ELEVENLABS_API_KEY=your-elevenlabs-key
```

> ⚠️ API 키를 설정/변경한 후 API/워커를 재시작해야 반영됩니다: `docker compose restart api worker`

### 모델 선택

프로젝트 생성 시 **Model Defaults** 섹션에서 로컬 모델과 원격 모델을 선택할 수 있습니다.
- **Local**: GPU 서비스 필요, 무료, 느림
- **Remote**: API 키 필요, 유료, 빠르고 고품질

원격 모델 옆에 ⚠️ 아이콘이 표시되면 해당 프로바이더의 API 키가 설정되지 않은 것입니다.

---

## 생성된 파일 위치

모든 생성물은 `data/artifacts/<run_id>/` 디렉토리에 저장됩니다:

```
data/artifacts/<run_id>/
├── scenes/
│   ├── scene-hook-1.png        # 섹션별 이미지
│   ├── scene-body-1.png
│   └── ...
├── audio/
│   └── audio.wav               # TTS 생성 오디오
├── subtitles/
│   └── subtitles.srt           # Whisper 생성 자막
└── render/
    └── output.mp4              # 최종 렌더링 영상 (1080x1920, H.264, 30fps)
```

---

## 제한 사항

### GPU 메모리

- GPU: NVIDIA GeForce GTX 1660 SUPER (6GB VRAM)
- GPU 서비스(Stable Diffusion, TTS, STT)를 동시에 실행할 수 없습니다
- GPU 잠금(Lock)이 사용되며, 하나의 GPU 작업이 완료되어야 다음 작업이 시작됩니다

### Worker 관련

- Docker Compose의 기본 worker는 `watchfiles`로 인해 파일 변경 시 재시작될 수 있습니다
- 안정적인 실행을 위해 standalone worker 사용을 권장합니다:

```bash
docker compose run -d --name sfp-worker-direct --no-deps \
  -e REDIS_URL=redis://redis:6379/0 \
  -e DATABASE_URL=postgresql://short_form_user:short_form_password@postgres:5432/short_form_studio \
  -e OLLAMA_BASE_URL=http://ollama:11434 \
  -e STABLE_DIFFUSION_BASE_URL=http://stable-diffusion:7860 \
  -e TTS_QWEN3_BASE_URL=http://tts-qwen3:8100 \
  -e STT_WHISPER_BASE_URL=http://stt-whisper:8200 \
  -e ARTIFACT_ROOT=data/artifacts \
  -e GPU_LOCK_KEY=gpu:lock \
  -e GPU_LOCK_TIMEOUT_SECONDS=600 \
  -e PYTHONPATH=/app/src:/app \
  worker celery -A celery_app.celery_app worker --loglevel=info --pool=solo
```

### 네트워크

- Studio Web과 API는 같은 Docker 네트워크에서 실행됩니다
- 외부 접근: `http://<LAN_IP>:5174` (Studio Web), `http://<LAN_IP>:8000` (API)
- Vite 프록시가 `/api` 경로를 API 서버로 자동 전달합니다

### 렌더링

- 영상 렌더링은 FFmpeg를 사용하며 로컬에서 실행됩니다
- 출력 형식: 1080x1920 (세로), H.264 코덱, 30fps
- 자막은 영상에 번인(burn-in) 처리됩니다
