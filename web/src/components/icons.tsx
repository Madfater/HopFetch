// - Line icons drawn on a 16-unit grid in the current text color; always hidden from assistive
//   tech, since the control that holds them carries its own name.

const PATHS = {
  pause: 'M5.5 3.5v9M10.5 3.5v9',
  resume: 'M5 3.2v9.6L12.5 8z',
  cancel: 'M4 4l8 8M12 4l-8 8',
  stop: 'M4.5 4.5h7v7h-7z',
  retry: 'M12.5 8a4.5 4.5 0 1 1-1.3-3.2M12.5 2.8v2.4h-2.4',
  save: 'M8 2.5v8M4.8 7.6 8 10.8l3.2-3.2M3 13.5h10',
  delete: 'M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5',
  minus: 'M3.5 8h9',
  plus: 'M8 3.5v9M3.5 8h9',
  copy: 'M6 6h7v7H6zM10 6V3H3v7h3',
  check: 'M3.5 8.5 6.5 11.5 12.5 4.5',
  chevron: 'M4.5 6.5 8 10l3.5-3.5',
} as const

export type IconName = keyof typeof PATHS

export function Icon({ name }: { name: IconName }) {
  return (
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor"
      strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d={PATHS[name]} />
    </svg>
  )
}

// - The mark of a file host, keyed by the provider's `icon` id; unknown ids get a plain box.
export function ProviderMark({ icon }: { icon: string }) {
  if (icon === 'k2s') {
    return (
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 18 18">
        <rect x="1" y="1" width="16" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M5.5 5v8M5.5 9.5 10 5M7.6 8.4 10.5 13" fill="none" stroke="currentColor" strokeWidth="1.5"
          strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="13" cy="11.5" r="1.5" fill="currentColor" />
      </svg>
    )
  }
  if (icon === 'mega') {
    return (
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 18 18">
        <rect x="1" y="1" width="16" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M5 12.5v-7l4 4.5 4-4.5v7" fill="none" stroke="currentColor" strokeWidth="1.5"
          strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }
  if (icon === 'mediafire') {
    return (
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 18 18">
        <rect x="1" y="1" width="16" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M9 13.5c-1.9 0-3.3-1.4-3.3-3.2 0-1.9 1.6-2.9 2.2-4.8.9.9 1.2 1.9 1.1 2.7.6-.4 1-1 1.2-1.8 1.2 1 2.1 2.3 2.1 3.9 0 1.8-1.4 3.2-3.3 3.2z"
          fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }
  if (icon === 'dropbox') {
    return (
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 18 18">
        <rect x="1" y="1" width="16" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M5 7.2 9 4.8l4 2.4-4 2.4zM5 7.2v3.6l4 2.4 4-2.4V7.2M9 9.6v3.6" fill="none" stroke="currentColor"
          strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }
  return (
    <svg aria-hidden="true" width="18" height="18" viewBox="0 0 18 18">
      <rect x="1" y="1" width="16" height="16" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  )
}
