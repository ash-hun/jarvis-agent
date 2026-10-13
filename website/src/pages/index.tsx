import type {ReactNode} from 'react';
import {Redirect} from '@docusaurus/router';
import useBaseUrl from '@docusaurus/useBaseUrl';

// 랜딩 페이지가 생기기 전까지 첫 화면은 소개 문서로 보낸다
export default function Home(): ReactNode {
  return <Redirect to={useBaseUrl('/intro')} />;
}
