# Chat surface: design-system boundary and accessibility contract

## Purpose

This document defines the UI-system boundary for the Kadode chat surface. It is
an inventory and implementation contract for presentation work; it does not
define conversation logic, idea decisions, project state, repositories, or API
behavior.

The intended visual direction is a quiet workspace surface: durable navigation,
one readable primary column, and clear content grouping. It takes cues from the
calm information hierarchy of Notion and Claude without copying either product.
Sakura is a small-area accent for orientation or emphasis, never the primary
surface color.

## Scope and boundary

### In scope for the product UI and design-system department

| Area | Responsibility | Reuse first |
| --- | --- | --- |
| Surface | Canvas, raised message/context surfaces, borders, empty and loading presentation | Existing semantic color tokens and Tailwind v4 utilities |
| Layout | Readable chat column, message rhythm, composer placement, desktop/mobile spacing | `WorkspaceChatPage` structural markup and standard flex/grid utilities |
| Navigation | Page location, scope selection appearance, responsive navigation affordances | `WorkspaceShell`, `SHELL_NAV`, and its `aria-current` convention |
| Tokens | Semantic colors, type scale, spacing, radii, focus, and reduced-motion behavior | Existing `--color-*` and `--motion-*` tokens before adding aliases |
| UI primitives | Buttons, field labels, textarea/composer, status region, message list, empty state | Native HTML elements styled with Tailwind v4 |
| Responsive behavior | 320px minimum support, compact navigation, touch targets, wrapping and overflow | Existing shell mobile drawer behavior and responsive utilities |
| Accessibility | Keyboard flow, visible focus, names/roles/states, live feedback, motion/contrast checks | Native semantics and existing `:focus-visible` / forced-colors rules |

### Explicitly out of scope

- `WorkspaceChatPage` message generation, send/decision handlers, scope data,
  local persistence, or repository behavior.
- Idea adoption, deferral, rejection, project creation, and every project or
  workflow state transition.
- `App.jsx` routing/integration, auth/runtime behavior, and API contracts.
- Changes to shared styles or `WorkspaceShell` until an integration assignment
  explicitly grants those files.

## Existing-component reuse inventory

Use the following order for a UI need: an existing component or convention,
standard React and Tailwind v4, a proven library when the interaction warrants
one, then a minimal local primitive. Do not introduce a parallel styled-component
foundation for this surface.

| Need | Existing asset or convention | Contract for a future UI change |
| --- | --- | --- |
| Workspace frame and mobile drawer | `WorkspaceShell` | Keep the shell as the owner of sidebar, mobile menu trigger, Escape dismissal, and current-page navigation. Chat content must not create a second global nav. |
| Chat content column | `WorkspaceChatPage` section/header/message/composer structure | Preserve the single primary reading column and `aria-labelledby="chat-heading"`; surface work may adjust classes or presentation only when file ownership is assigned. |
| Conversation scope switch | Native `button` elements with `aria-pressed` | Keep each option a real button, retain its pressed state, and give the group an accessible label. A future exclusive choice may use a documented tab or radio contract, not an unlabeled visual toggle. |
| Messages and feedback | Ordered list plus `aria-live="polite"`; `role="alert"` for failure | Keep messages in reading order. Announce new assistant content once, without moving focus; use assertive alerting only for errors requiring attention. |
| Composer | Native `form`, `label`, `textarea`, and submit button | Retain the programmatic label, native submit behavior, and a visible instruction for Enter versus Shift+Enter. |
| Controls and fields | Existing button/select/input/textarea focus rule | Meet a 44px minimum target where practical, retain visible focus, and do not substitute clickable `div` elements. |
| Plan/model controls | `ModelSelector` and native `select` elements | Reuse native label/select semantics and tokenized focus treatment when the chat surface needs a comparable selector. |
| Color and focus | `--color-canvas`, `--color-surface*`, `--color-text*`, `--color-border*`, `--color-action*`, `--color-focus` | Choose semantic tokens. Preserve the 3px `:focus-visible` outline, forced-colors compatibility, and high-contrast overrides. |

## Surface, layout, navigation, and token contract

### Surface hierarchy

1. **Canvas**: `--color-canvas`; only the application backdrop.
2. **Primary workspace surface**: `--color-surface`; persistent navigation and
   stable framing.
3. **Raised content**: `--color-surface-raised`; composer and primary reading
   regions when separation aids comprehension.
4. **Context and assistant grouping**: subtle neutral borders and low-contrast
   neutral fills; do not rely on color alone to identify speaker or state.
5. **User/action emphasis**: `--color-action` for the primary submit action.
6. **Sakura accent**: `--color-sakura-petal`, `--color-sakura-blush`, and
   `--color-sakura-ink` only for a compact marker, selected-detail edge, or
   limited candidate emphasis. It must not become a full-page background.

### Layout and responsiveness

- Desktop keeps navigation persistent and chat content in a readable, bounded
  column. The composer stays visually adjacent to the newest content without
  obscuring it.
- At narrow widths, use the shell drawer rather than duplicating navigation.
  Content must reflow down to 320px without horizontal scrolling, clipped focus
  outlines, or hidden composer actions.
- Message, context, and candidate sections stack in source/reading order.
  Controls may wrap but must keep an obvious label and a minimum 44px hit area.
- Dense metadata is secondary: use muted text, spacing, and headings before
  adding dividers or decorative cards.
- Respect `prefers-reduced-motion`; transitions are feedback only and never the
  sole indication that an operation occurred.

### Token usage

- Prefer semantic CSS variables already supplied by the shared stylesheet; do
  not hard-code product colors in chat JSX.
- Tailwind v4 utilities are the default expression layer. A token addition must
  represent a reusable semantic role, not one screen's color or spacing value.
- Text, borders, focus, error, pressed, disabled, and forced-colors states must
  remain distinguishable under the existing high-contrast mode.

## Accessibility acceptance criteria

### Keyboard

**Given** a keyboard-only user enters the chat page, **when** they press Tab,
**then** focus advances in visual and DOM order through the scope controls,
context, message content where interactive, composer, and submit control, with
a visible focus indicator that is not clipped.

**Given** focus is in the message textarea, **when** the user presses Enter,
**then** the form submits once; **when** they press Shift+Enter, **then** a
newline is inserted and no send occurs.

**Given** the user tabs to a scope control, **when** they activate it with
Enter or Space, **then** its `aria-pressed` state updates, the visible scope
changes, and focus remains on the activated control.

**Given** a mobile viewport has the workspace drawer open, **when** the user
presses Escape or activates the labelled close overlay, **then** the drawer
closes and focus returns to the menu trigger.

**Given** a control is disabled, **when** a keyboard user reaches adjacent
controls, **then** it communicates disabled state without trapping focus or
making the required next action ambiguous.

### Screen reader and semantic feedback

**Given** a screen-reader user enters chat, **when** the page loads, **then**
the page heading, chat scope label, context heading, and composer label expose
an understandable structure without requiring placeholder text.

**Given** a user switches scope, **when** the active option changes, **then**
the selected state is announced through its native button name and
`aria-pressed` state; the screen reader does not receive duplicate updates.

**Given** a new assistant reply is added, **when** rendering completes,
**then** the reply is announced once through a polite live region and keyboard
focus is not stolen from the composer.

**Given** chat hydration or persistence fails, **when** the error appears,
**then** it is announced assertively as an alert, explains the user impact in
plain language, and leaves existing draft content intact where possible.

**Given** messages appear in the transcript, **when** a screen reader reads
them, **then** each item identifies the speaker in text and follows the same
chronological order as the visual transcript.

### Visual and motion accessibility

**Given** a 390px-wide viewport, **when** the chat surface, scope controls,
transcript, and composer are rendered, **then** the page has no horizontal
scrolling, every focus outline remains fully visible, and the composer submit
action is visible and reachable without clipping, overlap, or a horizontal
gesture.

**Given** a desktop viewport of 1024px or wider, **when** the chat page is
rendered with a populated transcript, **then** persistent workspace navigation,
a single primary chat column, the composer, and polite live feedback are all
simultaneously present in a stable reading order.

**Given** a user enables forced colors or high contrast, **when** they view the
chat surface, **then** controls, text, borders, selected state, and focus
remain perceivable without relying on sakura or emerald color.

**Given** a user prefers reduced motion, **when** chat or navigation state
changes, **then** no required information depends on animation and transitions
are effectively removed by the shared motion rule.

## File-ownership proposal

This proposal keeps visual work separable from conversation and project logic.
It does not grant an implementation change by itself.

| File or area | Proposed owner | Change rule |
| --- | --- | --- |
| `docs/plans/design-system-chat-boundary.md` | Product UI and design system | Owns this boundary contract and its acceptance criteria. |
| `src/components/WorkspaceShell.jsx` | Workspace integration / shell owner | UI department may propose navigation/a11y requirements; edit only after a dedicated assignment. |
| `src/components/WorkspaceChatPage.jsx` | Conversation experience owner | Owns conversation behavior and state. UI department may receive a presentation-only sub-assignment with an agreed line-level boundary. |
| `src/App.jsx` | Integration owner | No UI-department edits without explicit integration assignment. |
| `src/styles.css` / shared token definitions | Shared design-system steward + integration approval | Token or global-style changes require a separately assigned PR to avoid cross-surface regressions. |
| New presentational primitives under `src/components/ui/` | Product UI and design system | Add only after reuse review; primitives must be behavior-light, native-semantic, documented, and covered by accessibility tests. |

## Review checklist for future chat-surface changes

- Does the diff reuse an existing component, native element, or token before
  adding a new primitive or style foundation?
- Does it leave chat logic, idea decisions, project state, repositories, App,
  and API contracts untouched unless separately assigned?
- Can a keyboard user complete scope selection and compose/send without a
  pointer, focus loss, or a focus trap?
- Are labels, pressed/disabled/error states, live feedback, and transcript
  speaker names exposed programmatically?
- At 390px, is there no horizontal scrolling, clipped focus indicator, or
  hidden/overlapped composer action?
- At desktop width (1024px or wider), are persistent navigation, one primary
  chat column, the composer, and polite live feedback all present in reading
  order?
- Does the viewport work at the 320px minimum, in forced colors, and with
  reduced motion?
- Has the owner verified UTF-8 text and `git diff --check` before review?
