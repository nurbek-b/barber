// Applies the saved/system theme before first paint (no flash). External file: the CSP
// for /admin/ allows only same-origin scripts.
try {
  var saved = localStorage.getItem("theme");
  var dark = saved ? saved === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.classList.toggle("dark", dark);
} catch {
  /* storage unavailable */
}
