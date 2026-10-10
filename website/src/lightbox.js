(() => {
  const triggers = document.querySelectorAll('.image-zoom');
  if (!triggers.length || typeof HTMLDialogElement === 'undefined' ||
      typeof HTMLDialogElement.prototype.showModal !== 'function') return;

  const dialog = document.createElement('dialog');
  dialog.className = 'screenshot-lightbox';
  dialog.setAttribute('aria-labelledby', 'lightbox-caption');
  dialog.innerHTML = '<div class="lightbox-panel"><button class="lightbox-close" type="button" aria-label="關閉圖片">關閉 <span aria-hidden="true">×</span></button><figure><img alt=""><figcaption id="lightbox-caption"></figcaption></figure></div>';
  document.body.append(dialog);
  const image = dialog.querySelector('img');
  const caption = dialog.querySelector('figcaption');
  const closeButton = dialog.querySelector('button');
  let opener;

  for (const trigger of triggers) {
    trigger.setAttribute('aria-haspopup', 'dialog');
    trigger.addEventListener('click', event => {
      event.preventDefault();
      opener = trigger;
      image.src = trigger.href;
      image.alt = trigger.querySelector('img').alt;
      caption.textContent = image.alt;
      dialog.showModal();
      document.documentElement.classList.add('lightbox-open');
      closeButton.focus({ preventScroll: true });
    });
  }

  closeButton.addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close();
  });
  dialog.addEventListener('cancel', event => {
    event.preventDefault();
    dialog.close();
  });
  dialog.addEventListener('close', () => {
    document.documentElement.classList.remove('lightbox-open');
    opener?.focus({ preventScroll: true });
  });
})();
