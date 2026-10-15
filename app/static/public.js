'use strict';

const cards = [...document.querySelectorAll('.app')];
function collapse(card) {
  card.classList.remove('is-expanded');
  card.querySelector('.app-info').setAttribute('aria-expanded', 'false');
  card.querySelector('.app-details').hidden = true;
}
cards.forEach((card) => {
  const button = card.querySelector('.app-info');
  button.addEventListener('click', () => {
    const expand = button.getAttribute('aria-expanded') !== 'true';
    cards.forEach(collapse);
    if (expand) {
      card.classList.add('is-expanded');
      card.querySelector('.app-details').hidden = false;
      button.setAttribute('aria-expanded', 'true');
    }
  });
});
document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  const expanded = document.querySelector('.app.is-expanded');
  if (expanded) { collapse(expanded); expanded.querySelector('.app-info').focus(); }
});
const search = document.querySelector('#app-search');
if (search) {
  const searchable = cards.map((card) => card.dataset.search.toLocaleLowerCase('de'));
  search.form.addEventListener('submit', (event) => event.preventDefault());
  search.addEventListener('input', () => {
    const query = search.value.trim().toLocaleLowerCase('de');
    cards.forEach((card, index) => {
      card.hidden = !searchable[index].includes(query);
      if (card.hidden) collapse(card);
    });
    document.querySelector('#no-results').hidden = cards.some((card) => !card.hidden);
  });
}
