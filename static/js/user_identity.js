(function () {
  const translationsNode = document.getElementById('navbar-translations');
  const translations = translationsNode
    ? JSON.parse(translationsNode.textContent || '{}')
    : {};
  const cookieName = 'username';
  const oneYearSeconds = 60 * 60 * 24 * 365;

  function readUsernameCookie() {
    const prefix = `${cookieName}=`;
    const entry = document.cookie.split(/;\s*/).find(value => value.startsWith(prefix));
    if (!entry) return '';
    try {
      return decodeURIComponent(entry.slice(prefix.length)).trim();
    } catch (_error) {
      return '';
    }
  }

  function saveUsername(username) {
    const attributes = [
      `${cookieName}=${encodeURIComponent(username)}`,
      `Max-Age=${oneYearSeconds}`,
      'Path=/',
      'SameSite=Lax',
    ];
    if (window.location.protocol === 'https:') attributes.push('Secure');
    document.cookie = attributes.join('; ');
  }

  let username = readUsernameCookie();
  while (!username) {
    const entered = window.prompt(translations.username_prompt || 'Enter a username (required):');
    username = (entered || '').trim();
    if (username) saveUsername(username);
  }
})();
