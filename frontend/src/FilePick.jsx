import { useRef } from 'react'

/* The file button.
 *
 * Every other control in the app is designed; the browser's own
 * "Choose Files / No file chosen" was the one piece of raw Chrome furniture
 * left, and on a phone it is small and says nothing about photos. This hides
 * the real input and drives it from a proper full-width button, so picking a
 * file looks like the rest of the app and reads the same on every device.
 *
 * The list of chosen files stays with the caller -- some screens upload
 * immediately, others hold the files until the form is submitted.
 */
export default function FilePick({
  onPick, multiple = true, disabled = false, accept,
  label = 'Add photo or file', busyLabel = 'Uploading…', busy = false,
}) {
  const ref = useRef(null)
  return (
    <>
      <input ref={ref} type="file" multiple={multiple} accept={accept}
        disabled={disabled || busy} hidden
        onChange={e => {
          const picked = [...e.target.files]
          e.target.value = ''            // same file twice in a row still fires
          if (picked.length) onPick(picked)
        }} />
      <button type="button" className="btn file-btn" disabled={disabled || busy}
        onClick={() => ref.current?.click()}>
        📎 {busy ? busyLabel : label}
      </button>
    </>
  )
}
