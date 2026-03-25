import { useEffect, useRef } from 'react'

export default function MatrixRain({ speed = 50 }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    let width = (canvas.width = window.innerWidth)
    let height = (canvas.height = window.innerHeight)
    
    const cols = Math.floor(width / 20)
    const ypos = Array(cols).fill(0)

    const handleResize = () => {
      width = canvas.width = window.innerWidth
      height = canvas.height = window.innerHeight
      // Re-init columns if needed, or just let them fall
    }
    window.addEventListener('resize', handleResize)

    const draw = () => {
      ctx.fillStyle = '#0001' // Fade out trail
      ctx.fillRect(0, 0, width, height)

      ctx.fillStyle = '#0f0'
      ctx.font = '15pt monospace'

      ypos.forEach((y, ind) => {
        const text = String.fromCharCode(Math.random() * 128)
        const x = ind * 20
        ctx.fillText(text, x, y)
        if (y > 100 + Math.random() * 10000) ypos[ind] = 0
        else ypos[ind] = y + 20
      })
    }

    const interval = setInterval(draw, speed)
    return () => {
      clearInterval(interval)
      window.removeEventListener('resize', handleResize)
    }
  }, [speed])

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        zIndex: 0,
        opacity: 0.3,
        pointerEvents: 'none',
      }}
    />
  )
}
