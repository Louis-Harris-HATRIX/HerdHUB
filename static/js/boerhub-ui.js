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

  const toggleButtons = document.querySelectorAll('[data-password-toggle]');
  toggleButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      const inputId = button.getAttribute('data-target');
      const input = inputId ? document.getElementById(inputId) : null;
      if (!input) {
        return;
      }

      const isHidden = input.type === 'password';
      input.type = isHidden ? 'text' : 'password';
      button.setAttribute('aria-pressed', String(isHidden));
      button.setAttribute('aria-label', isHidden ? 'Hide password' : 'Show password');

      const icon = button.querySelector('i[data-lucide]');
      if (icon) {
        icon.setAttribute('data-lucide', isHidden ? 'eye-off' : 'eye');
      }

      if (window.lucide) {
        window.lucide.createIcons();
      }
    });
  });

  if (window.lucide) {
    window.lucide.createIcons();
  }
});
