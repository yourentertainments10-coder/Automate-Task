/* Face recognition helper.
 *
 * The library and its ~6.8 MB of model weights are loaded LAZILY — only when
 * someone actually opens the camera — so the normal app stays light for
 * everyone who never uses face attendance.
 *
 * What leaves this file is a 128-number descriptor, never an image. The photo
 * is discarded the moment the descriptor is computed.
 */
let faceapi = null
let modelsReady = false
let loading = null

const MODEL_URL = '/models'

export async function loadFace(onProgress) {
  if (modelsReady) return faceapi
  if (loading) return loading
  loading = (async () => {
    onProgress?.('Loading face engine…')
    faceapi = await import('@vladmandic/face-api')
    onProgress?.('Loading face models…')
    await Promise.all([
      faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL),
      faceapi.nets.faceLandmark68Net.loadFromUri(MODEL_URL),
      faceapi.nets.faceRecognitionNet.loadFromUri(MODEL_URL),
    ])
    modelsReady = true
    return faceapi
  })()
  try {
    return await loading
  } catch (err) {
    loading = null
    throw new Error('Face models could not be loaded. Check your connection and try again.')
  }
}

/** Returns a plain array of 128 numbers, or throws a message meant for the user.
 *
 * Robustness rules learned from real office use:
 *  - THREE samples ~150ms apart are averaged — a single video frame is noisy
 *    (auto-exposure mid-adjustment, slight motion blur) and two single frames
 *    of the same person can drift past the match threshold.
 *  - When more than one face is visible (a colleague in the background), the
 *    LARGEST face — the person actually at the camera — is used, instead of
 *    refusing the scan.
 */
export async function describeFace(videoEl) {
  const api = await loadFace()
  const options = new api.TinyFaceDetectorOptions({ inputSize: 416, scoreThreshold: 0.5 })

  const samples = []
  for (let attempt = 0; attempt < 3; attempt++) {
    const results = await api
      .detectAllFaces(videoEl, options)
      .withFaceLandmarks()
      .withFaceDescriptors()
    if (results.length > 0) {
      const largest = results.reduce((a, b) =>
        (a.detection.box.area > b.detection.box.area ? a : b))
      samples.push(largest.descriptor)
    }
    if (attempt < 2) await new Promise(r => setTimeout(r, 150))
  }

  if (samples.length === 0) {
    throw new Error('No face detected. Look straight at the camera in good light.')
  }
  const avg = new Array(samples[0].length).fill(0)
  for (const d of samples) {
    for (let i = 0; i < avg.length; i++) avg[i] += d[i] / samples.length
  }
  return avg
}

export function isSupported() {
  return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)
}
