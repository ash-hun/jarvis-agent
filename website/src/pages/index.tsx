import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import useBaseUrl from '@docusaurus/useBaseUrl';

import styles from './index.module.css';

type Card = {title: string; body: string; to: string};

const PURPOSES: Card[] = [
  {
    title: '모델을 바꿔 가며 쓰고 싶다',
    body: '로컬 모델(Ollama, vLLM)과 클라우드 모델(Anthropic, OpenAI, Gemini)을 설정 한 줄로 바꾼다.',
    to: '/reference/configuration',
  },
  {
    title: '도구는 쓰되 위험한 명령은 막고 싶다',
    body: '파일, 셸, 웹 검색을 도구로 쓰고, 위험한 명령은 실행 전에 사람이 승인한다.',
    to: '/concepts/tools-and-approval',
  },
  {
    title: '먼저 챙겨 주는 비서가 필요하다',
    body: '흘린 약속을 기억하고, 정한 시각에 알리고, 할 말이 분명할 때만 먼저 말을 건다.',
    to: '/concepts/proactive',
  },
];

const PILLARS: Card[] = [
  {title: 'Inner Thought', body: '답하기 전에 따로 한 번 생각하고 그 판단을 남긴다.', to: '/concepts/inner-thought'},
  {title: 'Proactive 발화', body: '요청이 없어도 성찰해서, 가치가 분명할 때만 말을 건다.', to: '/concepts/proactive'},
  {title: 'Memory Management', body: '사실, 일화, 절차, 작업 패턴을 나눠 기억하고 다시 꺼낸다.', to: '/concepts/memory'},
  {title: 'Tool Accept System', body: '한 번 허용한 명령은 다시 묻지 않고, 성공한 작업은 절차로 남긴다.', to: '/concepts/tools-and-approval'},
  {title: 'Multi-agent Orchestration', body: 'JARVIS 옆에 KAREN 같은 에이전트를 파일 하나로 더하고 서로 일을 맡긴다.', to: '/concepts/team'},
];

function Cards({items, compact}: {items: Card[]; compact?: boolean}): ReactNode {
  return (
    <div className={compact ? styles.gridFive : styles.gridThree}>
      {items.map((c) => (
        <Link key={c.title} to={c.to} className={styles.card}>
          <span className={styles.cardTitle}>{c.title}</span>
          <span className={styles.cardBody}>{c.body}</span>
        </Link>
      ))}
    </div>
  );
}

export default function Home(): ReactNode {
  return (
    <Layout title="jarvis-agent" description="묻기 전에 먼저 생각하고 먼저 말을 거는 개인 AI 비서">
      <main className={styles.page}>
        <section className={styles.hero}>
          <p className={styles.label}>Own your custom agent like &quot;JARVIS&quot;</p>
          <h1 className={styles.title}>jarvis-agent</h1>
          <p className={styles.lead}>
            User를 적극적으로 도와주는 Personal AI Agent &quot;JARVIS&quot;입니다.
          </p>
          <div className={styles.actions}>
            <Link className="button button--primary button--lg" to="/start/install">
              설치하기
            </Link>
            <Link className="button button--secondary button--outline button--lg" to="/concepts/inner-thought">
              살펴보기
            </Link>
          </div>
          <img
            className={styles.shot}
            src={useBaseUrl('/img/hud-motion.gif')}
            alt="Web HUD 화면. 내적 사고, 마크다운 응답, 먼저 건네는 말, 승인 기억이 차례로 보인다"
          />
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>이런 사람에게 추천드립니다</h2>
          <Cards items={PURPOSES} />
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>대표 특징</h2>
          <Cards items={PILLARS} compact />
        </section>
      </main>
    </Layout>
  );
}
