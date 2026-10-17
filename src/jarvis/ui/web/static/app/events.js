// 서버 이벤트 라우터 — 웹소켓 메시지 하나를 화면 변화로 바꾼다. connected 는 session.js 가 먼저 받는다.
import { escapeHtml, renderMarkdown } from './markdown.js';
import { setStatus, logActivity, showLive, lastLine, CAPTION_HOLD_MS } from './shell.js';
import {
  appendMsg, appendThought, streamStart, streamDelta, streamEnd, lastStreamText,
  startToolTrace, endToolTrace,
} from './messages.js';
import { updateUsage } from './usage.js';
import { fetchAgenda, showNotice } from './agenda.js';
import { fetchTools } from './tools.js';
import { voice, isVoiceMode, clearVoiceMode, requestSpeech, takeSpeech, listenForApproval } from './voice-ui.js';
import { showApproval, closeApproval, approvalSpeech } from './approval.js';
import { askFeedback, isFeedbackPending, QUESTION_SPOKEN } from './proactive.js';
import { setInputEnabled, endAwaitingReply } from './composer.js';
import { isFullVoice } from './mode.js';
import { onReplyClassified } from './reply.js';
import { setActiveAgents } from './agents.js';
import { onFocusState, onFocusPanel } from './focus.js';

const ERROR_FLASH_MS = 3000;
let _agentStack = []; // [{name: string|null}, ...] — 서브 에이전트 계층 추적

function breadcrumb() {
  const names = _agentStack.map(a => a.name || '?').filter(Boolean);
  return names.length ? names.join(' → ') : null;
}

function showThinking() {
  const crumb = breadcrumb();
  setStatus(crumb ? `THINKING · ${crumb}` : 'THINKING', 'thinking');
  HUD.setState('thinking');
}

function flashError(message) {
  appendMsg('SYS', 'err', escapeHtml(message));
  logActivity(message, 'err');
  setStatus('ERROR', 'error');
  HUD.setState('error');
  setInputEnabled(true);
  setTimeout(() => { setStatus('READY'); HUD.setState('idle'); }, ERROR_FLASH_MS);
}

export function resetAgentStack() { _agentStack = []; }
export function isAgentBusy() { return _agentStack.length > 0; }

export function handleMessage(msg) {
  switch (msg.type) {

    case 'agent_start': {
      endAwaitingReply();
      const isRoot = _agentStack.length === 0;
      _agentStack.push({ name: msg.agent_name || null });
      if (!isRoot && msg.agent_name) logActivity(`↳ ${msg.agent_name}`);
      showThinking();
      if (isRoot) streamStart(); // 루트 에이전트만 메시지 컨테이너 초기화
      break;
    }

    case 'message_update':
      if (msg.text_delta) streamDelta(msg.text_delta);
      break;

    case 'stream_delta':
      streamDelta(msg.text);
      break;

    case 'agent_end': {
      if (_agentStack.length > 0) _agentStack.pop();
      if (_agentStack.length > 0) { showThinking(); break; }  // 서브 에이전트 종료 — 부모 계층으로 복귀

      // /focus 안내 뒤 메인 에이전트가 이어 돈다. 음성 요청이면 읽기와 승인 되묻기는 그 응답에서 한다
      if (msg.continues) { streamEnd(); break; }

      // 루트 에이전트 종료 — 메시지 확정 + 입력 복원
      streamEnd();
      setStatus('READY');
      HUD.setState('idle');
      fetchAgenda();  // 이번 턴의 inner thought 가 open loop 를 남겼을 수 있다
      fetchTools();   // /procedures approve 처럼 턴 안에서 도구가 늘었을 수 있다
      const usage = msg.final_message?.usage;
      if (usage) updateUsage(usage);
      if ((isVoiceMode() || isFullVoice()) && lastStreamText()) {
        requestSpeech(lastStreamText(), { thenListen: isFullVoice });
      } else {
        // 음성 요청에 말 없는 응답(도구만)이 오면 음성 처리 중 상태를 풀어 준다
        if (voice.state === 'processing') voice.setIdle();
        setInputEnabled(true);
      }
      clearVoiceMode();
      break;
    }

    case 'tool_execution_start': {
      const name = msg.tool_name || 'tool';
      const args = msg.args || {};
      const cmd  = args.command || args.query || (Object.keys(args).length ? JSON.stringify(args) : '');
      startToolTrace(msg.tool_call_id, name, cmd);
      logActivity(cmd ? `▸ ${name} · ${cmd}` : `▸ ${name}`, 'tool');
      setStatus('EXECUTING', 'executing');
      HUD.setState('tool_running');
      break;
    }

    case 'tool_execution_end': {
      const ok = !msg.is_error;
      const name = endToolTrace(msg.tool_call_id, ok);
      if (name) logActivity(`${ok ? '✓' : '✗'} ${name}`, ok ? 'ok' : 'err');
      setStatus('THINKING', 'thinking');
      HUD.setState('thinking');
      break;
    }

    case 'agent_error':
      streamEnd();
      flashError(msg.message || 'Unknown error');
      break;

    case 'error':
      voice.setIdle();  // TTS 오류면 '음성 처리 중' 상태를 풀어 준다
      flashError(msg.message || 'Error');
      break;

    case 'focus_state': {
      const st = msg.state || {};
      onFocusState(st);
      logActivity(st.active ? `◎ focus · ${Math.round((st.progress || 0) * 100)}%` : '◎ focus off');
      break;
    }

    case 'focus_panel':
      onFocusPanel(msg.area, msg.markdown || '', msg.busy);
      break;

    case 'inner_thought': {
      fetchAgenda();
      // 메인 응답과 구분된 메타인지 라인 (💭). interpretation이 없으면 표시 생략.
      const interp = (msg.interpretation || '').trim();
      if (interp) {
        const conf = Math.round((msg.confidence || 0) * 100);
        logActivity(`💭 ${msg.decision || 'silent'} · ${conf}%`);
        appendThought(interp, msg.decision || 'silent', conf);
      }
      break;
    }

    case 'proactive_message': {
      // 시스템 비요청 발화 — filler(💬 대기) / proactive·answer(🔔 먼저 건넨 말).
      const ptext = (msg.text || '').trim();
      if (!ptext) break;
      const isFiller = msg.kind === 'filler';
      const div = appendMsg(isFiller ? '💬' : '🔔', 'proactive', renderMarkdown(ptext));
      logActivity(`${isFiller ? '💬' : '🔔'} ${ptext}`, 'proactive');
      showLive(lastLine(ptext), CAPTION_HOLD_MS);
      // filler가 아닌 먼저 건넨 말엔 대화로 피드백을 묻는다 (C3). 다음 짧은 답이 수락/무시가 된다.
      const asks = !isFiller && !!msg.message_id;
      if (asks) askFeedback(div, msg.message_id);
      // voice 모드면 비요청 발화도 즉시 읽어준다. filler는 대기 체감을 줄이는 핵심.
      // Full-voice 는 피드백 질문까지 읽고 답을 듣는다.
      if (isFullVoice()) {
        requestSpeech(asks ? `${ptext} ${QUESTION_SPOKEN}` : ptext,
          { thenListen: () => asks && isFullVoice() && isFeedbackPending() });
      } else if (isVoiceMode() || msg.speak) {
        requestSpeech(ptext);
      }
      break;
    }

    case 'reminder':
      showNotice(msg);
      break;

    case 'approval_request': {
      // 음성으로 시작한 요청이면 Default 에서도 모달 대신 음성으로 되묻고 듣는다. 말로 일하던 중이다
      const byVoice = isFullVoice() || isVoiceMode();
      showApproval(msg.id, msg.command, msg.reason, msg.always_pattern, { voice: byVoice });
      logActivity(`⚡ approval · ${msg.command || ''}`, 'tool');
      if (byVoice) {
        listenForApproval();
        requestSpeech(approvalSpeech(msg.command, msg.always_pattern));
      }
      break;
    }

    case 'approval_resolved':
      if (closeApproval(msg.id)) {
        logActivity(msg.timeout ? '⚡ approval · 시간 초과로 거부' : '⚡ approval · 다른 창에서 처리됨', 'tool');
      }
      break;

    case 'voice_tts_audio':
      if (!takeSpeech(msg.id)) break;  // Esc 등으로 멈춘 읽기의 늦은 결과
      if (msg.data) {
        voice.playAudioBase64(msg.data, msg.mime || 'audio/wav');  // 백엔드 TTS (Supertonic-3 WAV)
      } else if (msg.text) {
        voice.speakBrowser(msg.text);  // 브라우저 TTS fallback
      } else {
        voice.setIdle();
      }
      break;

    case 'agent_activity':
      setActiveAgents(msg.active);
      break;
    case 'reply_classified':
      onReplyClassified(msg);
      break;

    case 'voice_stt_result':
      if (msg.error) {
        appendMsg('SYS', 'err', escapeHtml(`STT 오류: ${msg.error}`));
        voice.setIdle();
      } else if (msg.text && msg.text.trim()) {
        voice.receiveTranscript(msg.text);
      } else {
        appendMsg('SYS', 'err', '음성을 인식하지 못했습니다.');
        voice.setIdle();
      }
      break;
  }
}
