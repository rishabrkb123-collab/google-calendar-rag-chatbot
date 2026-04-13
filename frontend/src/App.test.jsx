import { render } from '@testing-library/react'
import { describe, it, expect } from 'vitest'

describe('App smoke test', () => {
  it('renders without crashing', () => {
    const { container } = render(<div>Calendar App</div>)
    expect(container).toBeTruthy()
  })
})
