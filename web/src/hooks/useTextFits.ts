import { useLayoutEffect, useState, type RefObject } from 'react'

// - Whether `text`, set in the input's own font, fits inside its content box without clipping.
// - Measured again whenever the input resizes or the text changes, so a narrow screen, a longer
//   language or more names all switch to the shorter copy on their own.
// - True where ResizeObserver or canvas text measuring is missing, as in jsdom.

let canvas: HTMLCanvasElement | null = null

function fits(input: HTMLInputElement, text: string): boolean {
  canvas ??= document.createElement('canvas')
  const context = canvas.getContext('2d')
  if (!context) return true
  const style = getComputedStyle(input)
  context.font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`
  const box = input.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
  return context.measureText(text).width <= box
}

export function useTextFits(ref: RefObject<HTMLInputElement | null>, text: string): boolean {
  const [fit, setFit] = useState(true)
  useLayoutEffect(() => {
    const input = ref.current
    if (!input || typeof ResizeObserver !== 'function') return
    const measure = () => setFit(fits(input, text))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(input)
    document.fonts?.ready.then(measure).catch(() => {})
    return () => observer.disconnect()
  }, [ref, text])
  return fit
}
