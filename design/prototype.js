document.addEventListener('click', (event) => {
  const chip = event.target.closest('[data-fill-topic]')
  if (chip) {
    const phone = chip.closest('.phone')
    const input = phone?.querySelector('[data-topic-input]')
    if (input) {
      input.value = chip.dataset.fillTopic || ''
      input.focus()
    }
  }

  const switchButton = event.target.closest('[data-switch]')
  if (switchButton) {
    const enabled = switchButton.classList.toggle('switch--on')
    switchButton.setAttribute('aria-checked', String(enabled))
  }
})
