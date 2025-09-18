import React, { useRef } from 'react'
import CanvasStage from './canvas/Stage'
import { useGraph } from './state/store'

export default function App() {
  const saveJSON = useGraph(s => s.saveJSON)
  const loadJSON = useGraph(s => s.loadJSON)
  const fileRef = useRef<HTMLInputElement>(null)

  const onSave = () => {
    const data = saveJSON()
    const blob = new Blob([data], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'fractal-outliner.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  const onOpen = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      try { loadJSON(String(reader.result)) } catch { alert('Invalid file') }
    }
    reader.readAsText(file)
  }

  return (
    <div style={{ height: '100vh', display: 'grid', gridTemplateRows: 'auto 1fr' }}>
      <div style={{ padding: 12, borderBottom: '1px solid #ddd', display: 'flex', gap: 8 }}>
        <button onClick={onSave}>Save</button>
        <button onClick={() => fileRef.current?.click()}>Open</button>
        <input ref={fileRef} type="file" accept="application/json" style={{ display: 'none' }} onChange={onOpen} />
      </div>
      <CanvasStage />
    </div>
  )
}
