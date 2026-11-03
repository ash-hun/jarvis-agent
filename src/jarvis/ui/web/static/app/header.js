// 헤더 가운데 묶음(점, 이름, 시각)을 리액터 구체의 가로 중심에 맞춘다. 좌우 카드 열 폭이 달라 창 가운데와 어긋난다.
const $header = document.querySelector('.header');
const $sphere = document.querySelector('.sphere-wrap');

function align() {
  const rect = $sphere.getBoundingClientRect();
  // 화면이 FLOW, SET 이어도 리액터는 자리를 지킨다(visibility). 폭이 0 이면 좁은 화면이라 창 가운데에 둔다
  if (!rect.width) { $header.style.removeProperty('--reactor-cx'); return; }
  const headerLeft = $header.getBoundingClientRect().left;
  $header.style.setProperty('--reactor-cx', `${rect.left + rect.width / 2 - headerLeft}px`);
}

new ResizeObserver(align).observe($sphere);
window.addEventListener('resize', align);
// Focus 는 열 폭을 애니메이션으로 바꾼다. 크기가 그대로인 채 자리만 옮겨도 끝에서 맞춘다
document.querySelector('.stage').addEventListener('transitionend', align);
align();
