# E.D.I.T.H. UI Changes

## Branding and app identity

- Renamed the product branding from MoChat to E.D.I.T.H across the UI, including the sidebar logo, AI response label, thinking status, browser tab title, and app metadata.
- Updated the saved theme/local storage keys to the new E.D.I.T.H naming to avoid stale UI state after the rebrand.

## Theme and color palette

- Set dark mode as the default, with a midnight navy chat canvas (`#0A0F1C`) and darker sidebar (`#070B14`).
- Updated dark mode accents to electric cyan (`#00E5FF`), with slate surfaces (`#131C31`), light text, and tactical red (`#FF5252`) for alerts.
- Updated light mode with a cool blue-tinted canvas and sidebar, cyan accents, and the same red alert color. The existing theme toggle still switches between dark and light modes.
- Applied cyan styling to the new-chat and E.D.I.T.H. logo marks, document count badge, and status indicator. The local model status dot has a cyan pulse.
- Changed the welcome mark from M to E, then removed the center badge at the user's request. The welcome heading and subtitle remain.

## Chat, citations, and effects

- Added a subtle cyan glow around the welcome mark (before its removal) and the focused chat input.
- Styled PDF citation chips with translucent cyan fills and cyan text, with a stronger treatment when selected.
- Updated the send button to cyan and retained red as the alert/citation accent.
- Added a translucent slate fill, cyan border, and backdrop blur to the dark-mode chat input and assistant response bubbles.

## HUD workspace background

- Added the supplied HUD graphic at `frontend/public/images/edith-hud-bg.jpg` and wired it into the main chat workspace only.
- The image is centered and cover-sized, using screen blending so its black areas blend with the navy canvas.
- The HUD layer fades between 22% opacity on the welcome screen and 7% when messages are present.
- Kept the sidebar opaque and layered above the workspace background. The HUD is hidden in light mode.

## Files updated

- `frontend/src/index.css` — theme color variables.
- `frontend/src/App.css` — workspace background, layering, glows, citation styling, and glass effects.
- `frontend/src/App.jsx` — dark default and active-chat background state.
- `frontend/src/components/EmptyState.jsx` — removed the center E badge.
- `frontend/public/images/edith-hud-bg.jpg` — supplied HUD image asset.
