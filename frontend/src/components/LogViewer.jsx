import React, { useState, useEffect, useRef } from 'react'
import { api } from '../App'

function LogViewer() {
  const [logs, setLogs] = useState([])
  const [selectedLog, setSelectedLog] = useState(null)
  const [logContent, setLogContent] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [lines, setLines] = useState(100)
  const [searchTerm, setSearchTerm] = useState('')
  const [autoRefresh, setAutoRefresh] = useState(false)
  const refreshInterval = useRef(null)

  // Fetch available logs
  const fetchLogs = async () => {
    try {
      const response = await api.get('/logs')
      setLogs(response.data.logs || [])
    } catch (err) {
      console.error('Failed to fetch logs:', err)
      setError('Failed to fetch available logs')
    }
  }

  // Fetch specific log content
  const fetchLogContent = async (logName, auto = false) => {
    if (!logName) return
    
    if (!auto) setLoading(true)
    try {
      const params = { lines }
      if (searchTerm) params.search = searchTerm
      
      const response = await api.get(`/logs/${encodeURIComponent(logName)}`, { params })
      setLogContent(response.data.content || 'No content')
      setSelectedLog(response.data)
      setError(null)
    } catch (err) {
      console.error('Failed to fetch log content:', err)
      if (!auto) setError(`Failed to fetch log: ${err.response?.data?.detail || err.message}`)
    } finally {
      if (!auto) setLoading(false)
    }
  }

  // Initial load
  useEffect(() => {
    fetchLogs()
  }, [])

  // Auto-refresh
  useEffect(() => {
    if (autoRefresh && selectedLog) {
      refreshInterval.current = setInterval(() => {
        fetchLogContent(selectedLog.name, true)
      }, 5000) // Refresh every 5 seconds
    }
    
    return () => {
      if (refreshInterval.current) {
        clearInterval(refreshInterval.current)
      }
    }
  }, [autoRefresh, selectedLog, lines, searchTerm])

  const handleLogSelect = (log) => {
    setSelectedLog(log)
    fetchLogContent(log.name)
  }

  const handleRefresh = () => {
    if (selectedLog) {
      fetchLogContent(selectedLog.name)
    }
    fetchLogs()
  }

  const formatSize = (bytes) => {
    if (bytes < 1024) return bytes + ' B'
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  }

  const getLogTypeIcon = (name) => {
    if (name.includes('celery')) return '📊'
    if (name.includes('fastapi') || name.includes('uvicorn')) return '🌐'
    if (name.includes('nginx')) return '🖥️'
    if (name.includes('error')) return '⚠️'
    if (name.includes('makemkv') || name.includes('DVD')) return '💿'
    return '📄'
  }

  return (
    <div className="log-viewer">
      <div className="page-header">
        <h1>Application Logs</h1>
        <div className="header-actions">
          <button 
            className="btn btn-secondary"
            onClick={handleRefresh}
            disabled={loading}
          >
            {loading ? 'Loading...' : '🔄 Refresh'}
          </button>
        </div>
      </div>

      {error && (
        <div className="alert alert-error">
          {error}
        </div>
      )}

      <div className="log-viewer-layout">
        {/* Log List Sidebar */}
        <div className="log-list-panel">
          <h3>Available Logs</h3>
          <div className="log-list">
            {logs.length === 0 ? (
              <p className="no-logs">No logs found</p>
            ) : (
              logs.map((log) => (
                <div
                  key={log.path}
                  className={`log-item ${selectedLog?.path === log.path ? 'active' : ''}`}
                  onClick={() => handleLogSelect(log)}
                >
                  <div className="log-item-icon">{getLogTypeIcon(log.name)}</div>
                  <div className="log-item-info">
                    <div className="log-item-name">{log.name}</div>
                    <div className="log-item-meta">
                      {formatSize(log.size)} • {new Date(log.modified).toLocaleString()}
                    </div>
                    <div className="log-item-desc">{log.description}</div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Log Content Panel */}
        <div className="log-content-panel">
          {selectedLog ? (
            <>
              <div className="log-content-header">
                <h3>{selectedLog.name}</h3>
                <div className="log-controls">
                  <label className="control-item">
                    Lines:
                    <select 
                      value={lines} 
                      onChange={(e) => {
                        setLines(Number(e.target.value))
                        fetchLogContent(selectedLog.name)
                      }}
                    >
                      <option value={50}>50</option>
                      <option value={100}>100</option>
                      <option value={250}>250</option>
                      <option value={500}>500</option>
                      <option value={1000}>1000</option>
                    </select>
                  </label>
                  
                  <label className="control-item">
                    <input
                      type="checkbox"
                      checked={autoRefresh}
                      onChange={(e) => setAutoRefresh(e.target.checked)}
                    />
                    Auto-refresh
                  </label>

                  <div className="search-box">
                    <input
                      type="text"
                      placeholder="Search in log..."
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      onKeyPress={(e) => e.key === 'Enter' && fetchLogContent(selectedLog.name)}
                    />
                    <button onClick={() => fetchLogContent(selectedLog.name)}>Search</button>
                  </div>
                </div>
              </div>

              <div className="log-stats">
                {selectedLog.lines_returned && (
                  <span>Showing {selectedLog.lines_returned} lines</span>
                )}
                {selectedLog.total_lines && (
                  <span> (of {selectedLog.total_lines} total)</span>
                )}
                {selectedLog.filtered_lines && (
                  <span> • Filtered: {selectedLog.filtered_lines} matches</span>
                )}
              </div>

              <div className="log-content">
                {logContent ? (
                  <pre>{logContent}</pre>
                ) : (
                  <p className="no-content">No content available</p>
                )}
              </div>
            </>
          ) : (
            <div className="no-selection">
              <p>Select a log file from the sidebar to view its contents</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default LogViewer
