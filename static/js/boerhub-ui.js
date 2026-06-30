document.addEventListener('DOMContentLoaded', function () {
  const splash = document.getElementById('boerhub-splash');
  if (splash) {
    window.setTimeout(function () {
      splash.classList.add('is-hidden');
    }, 450);
  }

  const forms = document.querySelectorAll('form');
  forms.forEach(function (form) {
    form.addEventListener('submit', function () {
      const submitButton = form.querySelector('button[type="submit"]');
      if (submitButton && !submitButton.dataset.keepLabel) {
        submitButton.disabled = true;
        submitButton.dataset.originalLabel = submitButton.textContent;
        submitButton.textContent = 'Saving...';
      }
    });
  });

  if (window.lucide) {
    window.lucide.createIcons();
  }
});
