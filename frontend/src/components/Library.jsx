import React, { useState, useEffect } from 'react'
import { api } from '../App'

function Library() {
  const [movies, setMovies] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [selectedMovie, setSelectedMovie] = useState(null)
  const [playingMovie, setPlayingMovie] = useState(null)

  // Edit / metadata search state
  const [editingMovie, setEditingMovie] = useState(null)
  const [activeTab, setActiveTab] = useState('manual')
  const [formData, setFormData] = useState({})
  const [searchTitle, setSearchTitle] = useState('')
  const [searchYear, setSearchYear] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    fetchMovies()
  }, [search])

  const fetchMovies = async () => {
    try {
      const params = search ? { search } : {}
      const response = await api.get('/library', { params })
      setMovies(response.data)
    } catch (err) {
      console.error('Failed to fetch library:', err)
    } finally {
      setLoading(false)
    }
  }

  const getStreamUrl = (id) => {
    const token = localStorage.getItem('token') || ''
    return `/api/library/${id}/stream?token=${encodeURIComponent(token)}`
  }

  const handlePlay = (e, movie) => {
    e.stopPropagation()
    setSelectedMovie(null)
    setPlayingMovie(movie)
  }

  const handleDelete = async (id, deleteFile = false) => {
    if (!confirm('Are you sure you want to delete this entry?')) return

    try {
      await api.delete(`/library/${id}`, { params: { delete_file: deleteFile } })
      fetchMovies()
      setSelectedMovie(null)
    } catch (err) {
      const detail = err.response?.data?.detail || err.message
      alert('Failed to delete: ' + detail)
    }
  }

  const openEdit = (movie) => {
    setEditingMovie(movie)
    setActiveTab('manual')
    setSearchTitle(movie.title || '')
    setSearchYear(movie.year || '')
    setSearchResults([])
    setFormData({
      title: movie.title || '',
      original_title: movie.original_title || '',
      year: movie.year || '',
      plot: movie.plot || '',
      genre: movie.genre || '',
      director: movie.director || '',
      cast: Array.isArray(movie.cast) ? movie.cast.join(', ') : (movie.cast || ''),
      runtime: movie.runtime || '',
      poster_url: movie.poster_url || '',
      backdrop_url: movie.backdrop_url || '',
      imdb_id: movie.imdb_id || '',
      tmdb_id: movie.tmdb_id || ''
    })
  }

  const closeEdit = () => {
    setEditingMovie(null)
    setSearchResults([])
  }

  const handleFormChange = (field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }))
  }

  const handleSave = async () => {
    if (!editingMovie) return
    setSaving(true)
    try {
      const payload = {
        ...formData,
        year: formData.year ? parseInt(formData.year, 10) : null,
        runtime: formData.runtime ? parseInt(formData.runtime, 10) : null,
        tmdb_id: formData.tmdb_id ? parseInt(formData.tmdb_id, 10) : null,
        cast: formData.cast
          ? formData.cast.split(',').map(s => s.trim()).filter(Boolean)
          : []
      }
      await api.put(`/library/${editingMovie.id}`, payload)
      await fetchMovies()
      closeEdit()
      setSelectedMovie(null)
    } catch (err) {
      const detail = err.response?.data?.detail || err.message
      alert('Failed to save: ' + detail)
    } finally {
      setSaving(false)
    }
  }

  const handleSearchMetadata = async () => {
    if (!searchTitle.trim()) return
    setSearchLoading(true)
    setSearchResults([])
    try {
      const params = { q: searchTitle.trim() }
      if (searchYear) params.year = searchYear
      const response = await api.get('/metadata/search', { params })
      setSearchResults(response.data.results || [])
    } catch (err) {
      const detail = err.response?.data?.detail || err.message
      alert('Search failed: ' + detail)
    } finally {
      setSearchLoading(false)
    }
  }

  const handleSelectResult = async (result) => {
    if (!editingMovie) return
    setSaving(true)
    try {
      await api.post(`/library/${editingMovie.id}/refetch-metadata`, {
        provider: result.provider,
        item_id: result.id
      })
      await fetchMovies()
      closeEdit()
      setSelectedMovie(null)
    } catch (err) {
      const detail = err.response?.data?.detail || err.message
      alert('Failed to update metadata: ' + detail)
    } finally {
      setSaving(false)
    }
  }

  const formatFileSize = (bytes) => {
    if (bytes === 0) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
  }

  if (loading) return <div className="loading">Loading library...</div>

  return (
    <div>
      <h1>Library</h1>

      <div className="search-box">
        <input
          type="text"
          placeholder="Search movies..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button className="btn btn-primary" onClick={fetchMovies}>Search</button>
      </div>

      {movies.length === 0 ? (
        <div className="card empty-state">
          <div className="empty-state-icon">🎬</div>
          <p>No movies in library yet. Start ripping some DVDs!</p>
        </div>
      ) : (
        <div className="movie-grid">
          {movies.map(movie => (
            <div
              key={movie.id}
              className="movie-card"
              onClick={() => setSelectedMovie(movie)}
            >
              <div className="movie-poster">
                {movie.poster_url ? (
                  <img src={movie.poster_url} alt={movie.title} />
                ) : (
                  '📀'
                )}
                <button
                  className="play-button"
                  onClick={(e) => handlePlay(e, movie)}
                  title="Play"
                >
                  ▶
                </button>
              </div>
              <div className="movie-info">
                <div className="movie-title">{movie.title}</div>
                {movie.year && (
                  <div className="movie-year">{movie.year}</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Movie Detail Modal */}
      {selectedMovie && (
        <div className="modal-overlay" onClick={() => setSelectedMovie(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{selectedMovie.title}</h3>
              <button
                className="btn btn-secondary"
                onClick={() => setSelectedMovie(null)}
              >
                ✕
              </button>
            </div>
            <div className="modal-body">
              <div style={{ display: 'flex', gap: 24 }}>
                <div style={{ width: 200, flexShrink: 0 }}>
                  {selectedMovie.poster_url ? (
                    <img
                      src={selectedMovie.poster_url}
                      alt={selectedMovie.title}
                      style={{ width: '100%', borderRadius: 8 }}
                    />
                  ) : (
                    <div className="movie-poster" style={{ height: 300 }}>📀</div>
                  )}
                </div>
                <div style={{ flex: 1 }}>
                  {selectedMovie.plot && (
                    <p style={{ marginBottom: 16 }}>{selectedMovie.plot}</p>
                  )}

                  <div style={{ display: 'grid', gap: 8, color: 'var(--text-muted)' }}>
                    {selectedMovie.year && (
                      <div><strong>Year:</strong> {selectedMovie.year}</div>
                    )}
                    {selectedMovie.genre && (
                      <div><strong>Genre:</strong> {selectedMovie.genre}</div>
                    )}
                    {selectedMovie.runtime && (
                      <div><strong>Runtime:</strong> {selectedMovie.runtime} min</div>
                    )}
                    <div><strong>File Size:</strong> {formatFileSize(selectedMovie.file_size)}</div>
                    <div><strong>Format:</strong> {selectedMovie.file_format}</div>
                    {selectedMovie.file_path && (
                      <div><strong>Location:</strong> {selectedMovie.file_path}</div>
                    )}
                  </div>
                </div>
              </div>
            </div>
            <div className="modal-footer">
              <button
                className="btn btn-primary"
                onClick={() => setPlayingMovie(selectedMovie)}
              >
                ▶ Play
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => openEdit(selectedMovie)}
              >
                ✎ Edit
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => handleDelete(selectedMovie.id, false)}
              >
                Remove Entry
              </button>
              <button
                className="btn btn-danger"
                onClick={() => handleDelete(selectedMovie.id, true)}
              >
                Delete File & Entry
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit / Metadata Modal */}
      {editingMovie && (
        <div className="modal-overlay" onClick={closeEdit}>
          <div className="modal edit-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Edit: {editingMovie.title}</h3>
              <button className="btn btn-secondary" onClick={closeEdit}>✕</button>
            </div>
            <div className="modal-body">
              <div className="edit-tabs">
                <button
                  className={`edit-tab ${activeTab === 'manual' ? 'active' : ''}`}
                  onClick={() => setActiveTab('manual')}
                >
                  Manual
                </button>
                <button
                  className={`edit-tab ${activeTab === 'search' ? 'active' : ''}`}
                  onClick={() => setActiveTab('search')}
                >
                  Search Online
                </button>
              </div>

              {activeTab === 'manual' && (
                <div className="edit-form">
                  <div className="form-row">
                    <label>Title</label>
                    <input
                      type="text"
                      value={formData.title}
                      onChange={(e) => handleFormChange('title', e.target.value)}
                    />
                  </div>
                  <div className="form-row">
                    <label>Original Title</label>
                    <input
                      type="text"
                      value={formData.original_title}
                      onChange={(e) => handleFormChange('original_title', e.target.value)}
                    />
                  </div>
                  <div className="form-row form-row-small">
                    <label>Year</label>
                    <input
                      type="number"
                      value={formData.year}
                      onChange={(e) => handleFormChange('year', e.target.value)}
                    />
                  </div>
                  <div className="form-row form-row-small">
                    <label>Runtime (min)</label>
                    <input
                      type="number"
                      value={formData.runtime}
                      onChange={(e) => handleFormChange('runtime', e.target.value)}
                    />
                  </div>
                  <div className="form-row">
                    <label>Genre</label>
                    <input
                      type="text"
                      value={formData.genre}
                      onChange={(e) => handleFormChange('genre', e.target.value)}
                      placeholder="e.g. Action, Comedy"
                    />
                  </div>
                  <div className="form-row">
                    <label>Director</label>
                    <input
                      type="text"
                      value={formData.director}
                      onChange={(e) => handleFormChange('director', e.target.value)}
                    />
                  </div>
                  <div className="form-row">
                    <label>Cast</label>
                    <textarea
                      value={formData.cast}
                      onChange={(e) => handleFormChange('cast', e.target.value)}
                      placeholder="Actor 1, Actor 2, ..."
                      rows={3}
                    />
                  </div>
                  <div className="form-row">
                    <label>Plot</label>
                    <textarea
                      value={formData.plot}
                      onChange={(e) => handleFormChange('plot', e.target.value)}
                      rows={5}
                    />
                  </div>
                  <div className="form-row">
                    <label>Poster URL</label>
                    <input
                      type="text"
                      value={formData.poster_url}
                      onChange={(e) => handleFormChange('poster_url', e.target.value)}
                    />
                  </div>
                  <div className="form-row">
                    <label>Backdrop URL</label>
                    <input
                      type="text"
                      value={formData.backdrop_url}
                      onChange={(e) => handleFormChange('backdrop_url', e.target.value)}
                    />
                  </div>
                  <div className="form-row form-row-small">
                    <label>IMDb ID</label>
                    <input
                      type="text"
                      value={formData.imdb_id}
                      onChange={(e) => handleFormChange('imdb_id', e.target.value)}
                    />
                  </div>
                  <div className="form-row form-row-small">
                    <label>TMDB ID</label>
                    <input
                      type="text"
                      value={formData.tmdb_id}
                      onChange={(e) => handleFormChange('tmdb_id', e.target.value)}
                    />
                  </div>
                </div>
              )}

              {activeTab === 'search' && (
                <div className="metadata-search">
                  <div className="search-row">
                    <input
                      type="text"
                      placeholder="Movie title"
                      value={searchTitle}
                      onChange={(e) => setSearchTitle(e.target.value)}
                    />
                    <input
                      type="number"
                      placeholder="Year (optional)"
                      value={searchYear}
                      onChange={(e) => setSearchYear(e.target.value)}
                      style={{ width: 140 }}
                    />
                    <button
                      className="btn btn-primary"
                      onClick={handleSearchMetadata}
                      disabled={searchLoading}
                    >
                      {searchLoading ? 'Searching...' : 'Search'}
                    </button>
                  </div>

                  {searchResults.length > 0 && (
                    <div className="search-results">
                      {searchResults.map((result) => (
                        <div
                          key={`${result.provider}-${result.id}`}
                          className="search-result"
                          onClick={() => handleSelectResult(result)}
                        >
                          <div className="search-result-poster">
                            {result.poster_url ? (
                              <img src={result.poster_url} alt={result.title} />
                            ) : (
                              '📀'
                            )}
                          </div>
                          <div className="search-result-info">
                            <div className="search-result-title">{result.title}</div>
                            <div className="search-result-meta">
                              {result.year && <span>{result.year}</span>}
                              <span className="provider-badge">{result.provider}</span>
                            </div>
                            {result.plot && (
                              <div className="search-result-plot">{result.plot}</div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {!searchLoading && searchResults.length === 0 && searchTitle && (
                    <p className="text-muted">No results found.</p>
                  )}
                </div>
              )}
            </div>
            <div className="modal-footer">
              {activeTab === 'manual' && (
                <button
                  className="btn btn-primary"
                  onClick={handleSave}
                  disabled={saving}
                >
                  {saving ? 'Saving...' : 'Save Changes'}
                </button>
              )}
              <button className="btn btn-secondary" onClick={closeEdit}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {/* Video Player Overlay */}
      {playingMovie && (
        <div className="modal-overlay video-overlay" onClick={() => setPlayingMovie(null)}>
          <div className="video-modal" onClick={(e) => e.stopPropagation()}>
            <div className="video-modal-header">
              <h3>{playingMovie.title}</h3>
              <button
                className="btn btn-secondary"
                onClick={() => setPlayingMovie(null)}
              >
                ✕
              </button>
            </div>
            <div className="video-container">
              <video
                controls
                autoPlay
                src={getStreamUrl(playingMovie.id)}
                onError={async (e) => {
                  console.error('Video playback error:', e)
                  const streamUrl = getStreamUrl(playingMovie.id)
                  let detail = ''
                  try {
                    // Probe the stream to surface the real HTTP error
                    await api.get(streamUrl, {
                      responseType: 'blob',
                      headers: { Range: 'bytes=0-0' }
                    })
                  } catch (err) {
                    detail = err.response?.status
                      ? ` (HTTP ${err.response.status}: ${err.response?.data?.detail || err.message})`
                      : ` (${err.message})`
                  }
                  alert('Unable to play this video.' + detail + '\n\nThe file may be missing, on a remote storage destination, or in an unsupported format.')
                  setPlayingMovie(null)
                }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Library
