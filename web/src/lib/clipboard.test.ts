import { describe, expect, it } from 'vitest'
import { pathSegments } from './clipboard'

describe('pathSegments', () => {
  it('ends each segment at its separator', () => {
    expect(pathSegments('/volume1/downloads/hop')).toEqual(['/', 'volume1/', 'downloads/', 'hop'])
    expect(pathSegments('/data/')).toEqual(['/', 'data/'])
    expect(pathSegments('C:\\Users\\me')).toEqual(['C:\\', 'Users\\', 'me'])
    expect(pathSegments('plain')).toEqual(['plain'])
  })
})
