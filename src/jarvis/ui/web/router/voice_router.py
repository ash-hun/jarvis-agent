"""[ui] 음성 REST: 미리 녹음한 읽기 문구의 wav 를 이름으로 내준다."""

from fastapi import APIRouter, Path
from fastapi.responses import FileResponse, JSONResponse, Response

from jarvis.ui.web.web_state import WebState

PHRASE_NAME_DOC = "문구 이름. connected.voice.phrases 에 온 이름 중 하나"


def build_voice_router(state: WebState) -> APIRouter:
    router = APIRouter(tags=["voice"])

    @router.get(
        "/api/voice/phrases/{name}",
        summary="읽기 문구 wav",
        description=(
            "JARVIS_VOICE__PHRASES_DIR 의 phrases.json 에 있는 문구 하나의 wav."
            " 화면은 이벤트(도구 시작, Focus 전환, 웨이크워드 등)에 맞춰 합성 대신 이 파일을 재생한다."
        ),
        response_class=Response,
        responses={
            200: {"content": {"audio/wav": {}}},
            404: {"content": {"application/json": {"example": {"error": "unknown phrase: hello"}}}},
        },
    )
    async def phrase_audio(name: str = Path(description=PHRASE_NAME_DOC)) -> Response:
        wav = state.phrases.get(name)
        if wav is None:
            return JSONResponse({"error": f"unknown phrase: {name}"}, status_code=404)
        return FileResponse(wav, media_type="audio/wav")

    return router
