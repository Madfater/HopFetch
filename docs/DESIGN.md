---
name: Hop fetch
description: A dark, quiet NAS download dashboard colored like a long night-sky exposure.
colors:
  night-ground: "#0c1220"
  indigo-shell: "#171443"
  panel-plate: "#141b2c"
  raised-face: "#1b2539"
  deep-well: "#050914"
  well-edge-top: "#02040b"
  well-edge-bottom: "#283348"
  field-edge: "#6c7b96"
  selected-indigo: "#585aa0"
  star-white: "#e7eef5"
  mist-blue: "#a0aec1"
  divider: "#1d2535"
  oiii-teal: "#4dd4db"
  pale-green: "#9cdd76"
  h-alpha-red: "#f35863"
  h-alpha-red-text: "#f8767a"
  star-gold: "#f4cb75"
  on-light: "#090f1c"
typography:
  brand:
    fontFamily: "Archivo Variable, system-ui, sans-serif"
    fontSize: "2rem"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.01em"
    fontVariation: "'wdth' 125"
  headline:
    fontFamily: "Archivo Variable, system-ui, 'PingFang TC', 'Microsoft JhengHei', 'Noto Sans TC', sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.2
    fontVariation: "'wdth' 112.5"
  title:
    fontFamily: "system-ui, 'PingFang TC', 'Microsoft JhengHei', 'Noto Sans TC', sans-serif"
    fontSize: "1.05rem"
    fontWeight: 600
    lineHeight: 1.5
  body:
    fontFamily: "system-ui, 'PingFang TC', 'Microsoft JhengHei', 'Noto Sans TC', sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  secondary:
    fontFamily: "system-ui, 'PingFang TC', 'Microsoft JhengHei', 'Noto Sans TC', sans-serif"
    fontSize: "0.9rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "system-ui, 'PingFang TC', 'Microsoft JhengHei', 'Noto Sans TC', sans-serif"
    fontSize: "0.85rem"
    fontWeight: 600
    lineHeight: 1.5
  numeric:
    fontFamily: "Archivo Variable, system-ui, sans-serif"
    fontFeature: "tnum"
rounded:
  s: "4px"
  m: "8px"
  l: "14px"
  round: "999px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "24px"
  "6": "40px"
components:
  button-primary:
    backgroundColor: "{colors.star-gold}"
    textColor: "{colors.on-light}"
    rounded: "{rounded.m}"
    padding: "0 16px"
    height: "36px"
  button-secondary:
    backgroundColor: "{colors.panel-plate}"
    textColor: "{colors.star-white}"
    rounded: "{rounded.m}"
    padding: "0 16px"
    height: "36px"
  button-secondary-hover:
    backgroundColor: "{colors.raised-face}"
  button-danger:
    backgroundColor: "{colors.panel-plate}"
    textColor: "{colors.h-alpha-red-text}"
    rounded: "{rounded.m}"
    padding: "0 16px"
    height: "36px"
  button-danger-hover:
    backgroundColor: "{colors.h-alpha-red}"
    textColor: "{colors.on-light}"
  icon-button:
    textColor: "{colors.star-white}"
    rounded: "{rounded.m}"
    size: "32px"
  input-slot:
    backgroundColor: "{colors.deep-well}"
    textColor: "{colors.star-white}"
    rounded: "{rounded.l}"
    padding: "0 16px 0 24px"
    height: "56px"
  plate:
    backgroundColor: "{colors.panel-plate}"
    rounded: "{rounded.l}"
    padding: "16px 24px"
  nav-bar:
    backgroundColor: "{colors.indigo-shell}"
    textColor: "{colors.mist-blue}"
    height: "52px"
  nav-count:
    textColor: "{colors.oiii-teal}"
    rounded: "{rounded.round}"
    height: "20px"
  switch-off:
    backgroundColor: "{colors.deep-well}"
    rounded: "{rounded.round}"
    width: "44px"
    height: "24px"
  switch-on:
    backgroundColor: "{colors.star-gold}"
    rounded: "{rounded.round}"
    width: "44px"
    height: "24px"
  segment-selected:
    backgroundColor: "{colors.selected-indigo}"
    textColor: "{colors.star-white}"
    rounded: "{rounded.m}"
    height: "30px"
  progress-track:
    backgroundColor: "{colors.deep-well}"
    rounded: "{rounded.round}"
    height: "6px"
  progress-fill-active:
    backgroundColor: "{colors.oiii-teal}"
    rounded: "{rounded.round}"
  progress-fill-failed:
    backgroundColor: "{colors.h-alpha-red}"
    rounded: "{rounded.round}"
---

# Design System: Hop fetch

## Overview

**Creative North Star: "The Long Exposure"**

A download is an astrophotography exposure: many short sub-exposures stacked into one image while nobody watches, the way byte ranges stack into one file on the NAS. The dashboard is the night sky around that exposure. The ground is blue-black, the navigation is a deeper indigo band, text is star-white, and color only appears where the narrowband lines of a long exposure would: teal for light still being collected, pale green for a finished frame, red for a failure. Star gold is not a state at all. It is the operator's hand, and it marks only the places the operator acts.

The interface is dark only, by product commitment. Surfaces are flat and quiet; the input slot on the Download page is the one deep element, and the star grain of the progress fill is the one signature texture: bright on running work, faint and still on finished work, so the sky never goes empty when nothing is downloading. The operator should be able to glance at the task list, see which rows are still collecting light, which are done and which need them, and leave.

The palette is defined as role-named CSS custom properties in `web/src/styles/tokens.css`, derived from OKLCH with hue 264 for the neutrals and written as hex. A light theme is not part of the product, so the token set holds one dark set of values.

**Key Characteristics:**
- Blue-black ground, indigo navigation band carried into the scrollbar gutter, star-white text.
- Three state colors (teal, green, red), each always paired with a text label.
- Star gold reserved for the operator's own actions and keyboard focus.
- Flat plates; depth only where it encodes elevation.
- A star-grain progress fill that slides in with the bytes, and stays faintly in finished frames.
- Archivo with a width axis for the name, page titles and every number; system text everywhere else, including Chinese.

## Colors

A cold night sky with three narrowband state lines and one warm gold for the human hand.

### Primary
- **Star Gold** (#f4cb75, oklch(86% 0.115 85)): the operator's hand. The one primary button of a page, the 2px underline of the current tab, a switch the operator turned on, the keyboard focus outline (`--color-focus` holds the same value), the dashed edge of a drop target, text selection (gold mixed 35% into the ground) and the text caret. Text on gold is On-Light Ink.

### Secondary
- **OIII Teal** (#4dd4db, oklch(80% 0.115 200)): work in progress. Lamps for checking, queued, downloading and unsaved settings, the active progress fill, the 1px ring of a queued progress track, and the count chip on the Downloads tab (teal text on teal mixed 16% into the shell).
- **Pale Green** (#9cdd76, oklch(83% 0.15 135)): finished work and links that can be downloaded. Completed progress fills use it mixed 60% into the well, with the star grain showing through a 75% wash of that mix, so finished rows sit quieter than running ones.
- **H-Alpha Red** (#f35863, oklch(67% 0.19 20)): failure. Failed lamps, failed progress fills, the ring and 28% tint of a failed progress track, and the danger button's hover face.
- **H-Alpha Red Text** (#f8767a): every error text, the danger button outline, the invalid slot edge and the offline banner. It is lighter than H-Alpha Red so it keeps 4.5:1 on the raised face.

### Neutral
- **Night Ground** (#0c1220): the page.
- **Indigo Shell** (#171443): the navigation band, the top 52px of the scrollbar track, the favicon tile and the browser `theme-color`.
- **Panel Plate** (#141b2c): settings plates, the link preview, dialogs, toasts, secondary buttons and the hovered table row.
- **Raised Face** (#1b2539): hovered buttons, icon-button hover, tooltips and keyboard keys.
- **Deep Well** (#050914): recessed elements: the input slot, switch track, segmented-control track, number stepper and progress tracks.
- **Well Edge Top** (#02040b) and **Well Edge Bottom** (#283348): the dark upper and lighter lower borders that cut a well into its surface. Well Edge Bottom is also the general control border and the table header rule.
- **Field Edge** (#6c7b96): the lit lower edge of the input slot and the switch border, 3:1 against the plate so a field reads as a control; also the scrollbar thumb.
- **Selected Indigo** (#585aa0): the face of the chosen segment in a segmented control, drawn from the shell, 3:1 against its track.
- **Star White** (#e7eef5): primary text.
- **Mist Blue** (#a0aec1): secondary text, inactive tabs, table headers, paused and canceled lamps, the off switch knob, the ring of a canceled progress track and paused fills (mixed 62% into the well). It keeps 4.5:1 on every surface.
- **Divider** (#1d2535): table row rules and plate borders.
- **On-Light Ink** (#090f1c): dark text on a gold, teal, green or red face.

### Named Rules
**The Hand Is Not a Lamp Rule.** Star gold never marks a state. Only something the operator does or chose (a primary action, the current tab, an on switch, focus, a drop target, a selection) is gold. Anything the system reports uses teal, green, red or mist blue.

**The Label Beside Every Light Rule.** A state color always appears next to its text label. Color is never the only carrier of status.

**The Only Running Work Is Bright Rule.** Full-strength teal and red are for work in progress and failures. Finished and paused work is drawn in dimmed mixes so the eye lands on what is still moving or needs a decision. A finished fill may keep the star grain only at a fraction of its strength, still, with no lit edge and no glow.

## Typography

**Display Font:** Archivo Variable with its width axis, self-hosted through Fontsource and preloaded (with system-ui fallback)
**Body Font:** system-ui, then PingFang TC, Microsoft JhengHei, Noto Sans TC, sans-serif

**Character:** a wide, sturdy grotesque for the name, page titles and figures against the platform's own text face, so Chinese and English copy read natively and numbers line up like instrument readouts.

### Hierarchy
- **Brand** (700, 2rem, 1.1, width 125%, -0.01em): the product name above the Download slot, in star-white, set as live text. It stays smaller than the slot is tall, so the slot still leads.
- **Headline** (600, 1.5rem, 1.2, width 112.5%): page titles such as Downloads and Settings.
- **Title** (600, 1.05rem to 1.1rem): plate titles in Settings, dialog titles and the empty-state title.
- **Body** (400, 15px root, 1.5): all running text; the slot input sets 1rem.
- **Secondary** (400, 0.9rem): hints, plate descriptions, supported sites.
- **Label** (600, 0.85rem): table headers; the same size at regular weight carries notes under names, speeds and tooltips. The nav count chip uses 0.8rem.
- **Numeric** (Archivo Variable, `tabular-nums`): every size, percentage, speed, count and stepper value, through the `.num` class.

### Named Rules
**The Figures Are Archivo Rule.** Any number the operator reads goes through `.num`: Archivo with tabular figures, so columns of sizes and percentages align.

**The Sentence Case Rule.** Labels are sentence case in English. No all-caps labels, no letter-spaced small caps, no monospace data labels. The one monospace value is the download folder path in Settings, which wraps only after its separators.

## Layout

The Download page is a single centered column at most 560px wide, starting 10vh down, so the slot leads the page. Downloads uses a 1200px frame with the table aligned left. Settings is a 720px column of plates on the same axis. The navigation band spans the window; its content sits in the same 1200px frame, 52px tall, with a 24px gap between tabs.

Spacing follows a 4, 8, 12, 16, 24, 40px scale. Pages pad 24px top, 16px sides and 40px bottom; plates pad 16px by 24px; table cells pad 12px.

The scrollbar gutter is always reserved so the centered frame never shifts between pages. Below 768px each task row becomes a grid (name and notes, status over host and size, progress beside the actions). Below 560px a settings control moves under its text. Below 480px nav gaps tighten to 16px and segments lose padding. On coarse pointers icon buttons grow to 44px targets.

## Elevation & Depth

Depth encodes elevation only, through three shadow tokens and tonal steps from well to ground to panel to raised. Recessed fields sink with an inset shade; flush plates and buttons carry a 1px top highlight; floating layers (dialogs, toasts, tooltips) add a soft drop shade. The only glow in the system belongs to lit lamps.

### Shadow Vocabulary
- **Recess** (`box-shadow: inset 0 1px 3px rgb(0 2 10 / 55%)`): the input slot, switch track, segmented-control track and number stepper.
- **Plate** (`box-shadow: inset 0 1px 0 rgb(200 215 255 / 7%)`): nav bar, settings plates, preview, secondary buttons and the chosen segment.
- **Float** (`box-shadow: inset 0 1px 0 rgb(200 215 255 / 7%), 0 12px 32px rgb(0 2 10 / 55%)`): dialogs, toasts and tooltips.
- **Lamp glow** (`0 0 2px 1px` at 85% plus `0 0 12px 3px` at 30% of the lamp color, on `::after`): lit lamps only; it breathes on opacity for running work.

### Named Rules
**The One Deep Slot Rule.** The Download input slot is the deepest element on any page: deep well face, darker top and left edges, a lit field-edge bottom, and the recess shade. Nothing else on that page is sunk that far.

**The Starlight Belongs to Lamps Rule.** Glow is a lamp property. Teal and red lamps shine; a done lamp is lit but casts no glow; no other element glows.

## Shapes

Corners are gentle and consistent: 4px for tooltips and keys, 8px for buttons, icon buttons and segmented controls, 14px for the slot, plates, preview, dialogs and toasts, and full pills for lamps, switches, chips, progress tracks and the scrollbar thumb. Borders are 1px; a well is drawn with a darker top and a lighter bottom edge rather than a uniform stroke.

## Components

### Buttons
- **Shape:** gently rounded (8px), at least 36px tall, 16px side padding, weight 500.
- **Primary:** star-gold face with On-Light Ink text at weight 600 and a 45% white top highlight; one per page. Hover lightens the gold 25% toward white.
- **Secondary:** panel face, Well Edge Bottom border, plate highlight; hover shifts to the raised face.
- **Danger:** red-text outline and label; pointed at, it fills H-Alpha Red with dark text.
- **Press and disabled:** press drops 1px; disabled drops its face and highlight, keeps a Well Edge Bottom frame and turns mist blue, so it still reads as a button that cannot be pressed yet.
- **Icon button:** 32px, transparent until hovered, then a raised face with a border; press scales to 0.92. Icons are inline SVG.

### Input slot
- **Style:** deep well face, 14px radius, 56px tall, 24px left padding; edges as in The One Deep Slot Rule.
- **Focus:** a gold outline that eases out from the edge to 3px offset.
- **Invalid:** the whole edge turns red text color.
- **Drop target:** the edge turns dashed gold over a 6% gold tint.

### Plates
- **Corner Style:** 14px.
- **Background:** panel plate with a divider border and the plate highlight.
- **Internal Padding:** 16px by 24px; settings rows are parted by a 1px groove in the ground color.

### Navigation
- Indigo shell band 52px tall with a divider bottom rule and plate highlight, sticky at the top. Tabs are mist blue and turn star white on hover or when current. The current tab carries a 2px gold underline with rounded top corners that slides between tabs as its own view transition. Active tasks show a teal count chip; failures show a red lamp and count.

### Lamps
- A 10px circle with a 2px border in its lamp color. Solid or hollow by state: queued hollow teal, downloading solid teal, paused solid mist, canceled hollow mist, done solid green without glow, failed red. Running lamps breathe their glow; a lamp that changes state blinks once from 55% scale.

### Switch and segmented control
- **Switch:** 44 by 24px pill. Off is a well with a field-edge border and a mist knob; on is solid gold with a ground-colored knob. The knob is a clipped pill that stretches toward the middle while pressed.
- **Segmented control:** a recessed well track with 3px padding; the chosen segment is a Selected Indigo face that slides between segments. An overflowing track scrolls inside itself and fades its right edge.

### Progress fill (signature)
A 6px pill track in the deep well with a dark top edge. The fill always spans the full track width and slides in from the left by transform over 500ms linear, so its texture never stretches. Any visible fill is at least 8px long, so a few percent still reads as a bar. A downloading fill is teal carrying an irregular grain of brighter points from one authored 60px SVG tile, with a 3px leading edge lit 30% toward white: a strip of the stack, still collecting light. Completed fills settle to green mixed 60% into the well and keep the same grain tile, static, under a 75% wash of that green, so a finished frame keeps faint stars without an edge or glow; paused fills to mist mixed 62% into the well, failed fills to solid red. The track repeats the status lamp so empty bars still differ: a queued track carries a 1px teal inner ring, a canceled one a mist ring, and a failed one a red ring over the well tinted 28% red.

### Motion
Fast (120ms) for hover, press and tooltips; base (200ms) for toggles and small entrances; slow (320ms) for the preview sliding out from under the slot and for page-level pops. Everything that enters or moves decelerates on `cubic-bezier(0.2, 0.8, 0.2, 1)` with no overshoot; exits use a short ease-in. Pages crossfade on opacity while the header and toasts hold still. Under reduced motion every animation completes at once.

## Do's and Don'ts

### Do:
- **Do** take every color from a role token in `tokens.css`; mix with `color-mix(in oklab, ...)` when a dimmer state is needed.
- **Do** keep star gold (#f4cb75) for the operator's own actions and focus, and keep one gold primary button per page.
- **Do** pair every lamp or state color with its text label.
- **Do** set every number in Archivo with tabular figures through `.num`.
- **Do** draw recessed controls as wells (#050914) with a darker top edge, and floating layers with the float shadow.
- **Do** keep muted text at 4.5:1 on every surface and control edges at 3:1 against their plate.

### Don't:
- **Don't** use gold for a status, or teal, green or red for an action.
- **Don't** add glow to anything but a lit lamp, or a drop shade to anything that does not float.
- **Don't** add gradients for decoration; gradients appear only as hard-stop devices (the progress leading edge, the shell band in the scrollbar gutter) and the overflow fade mask.
- **Don't** set English labels in all caps, or data labels in a monospace face; only the download folder path is monospace.
- **Don't** join facts with a middle dot or end link and button text with an arrow.
- **Don't** wrap every block in a rounded card; the task list is a bare table on the ground.
- **Don't** add a light theme.
