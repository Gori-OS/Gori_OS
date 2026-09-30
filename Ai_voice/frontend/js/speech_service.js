/**
 * SpeechService — Real-time Speech-to-Text via AssemblyAI Streaming (v3 WebSocket)
 * Handles token fetching, browser microphone capture, PCM 16-bit encoding,
 * live partial/final transcription streaming, and graceful session termination.
 */
class SpeechService {
    constructor() {
        this.socket = null;
        this.audioContext = null;
        this.mediaStream = null;
        this.scriptProcessor = null;
        this.state = 'stopped'; // 'requesting_mic' | 'listening' | 'processing' | 'stopped' | 'error'
        this.terminateResolve = null;
        this.lastProcessedTurnOrder = null;

        // Callbacks
        this.onPartial = null;       // (transcript: string, meta?: object) => void
        this.onFinal = null;         // (transcript: string, meta?: object) => void
        this.onError = null;         // (errorMessage: string) => void
        this.onStateChange = null;   // (state: string) => void
    }

    setState(newState) {
        this.state = newState;
        if (typeof this.onStateChange === 'function') {
            try {
                this.onStateChange(newState);
            } catch (e) {
                console.error('[SpeechService] onStateChange callback error:', e);
            }
        }
    }

    reportError(message) {
        this.cleanup();
        this.setState('error');
        if (typeof this.onError === 'function') {
            try {
                this.onError(message);
            } catch (e) {
                console.error('[SpeechService] onError callback error:', e);
            }
        }
    }

    isActive() {
        return this.state === 'listening' || this.state === 'requesting_mic' || this.state === 'processing';
    }

    isListening() {
        return this.state === 'listening';
    }

    async start() {
        // 1. Guard against double-start
        if (this.state === 'listening' || this.state === 'requesting_mic' || this.state === 'processing') {
            console.warn('[SpeechService] start() ignored: already running or starting (state=' + this.state + ')');
            return;
        }

        // 2. Insecure context & getUserMedia detection
        // Browser mic capture requires HTTPS or http://localhost. Opening http://<LAN-IP>:7890 blocks getUserMedia.
        const isSecure = window.isSecureContext || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
        if (!isSecure || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            this.reportError('Microphone access blocked: Browsers require a secure context (http://localhost or HTTPS). Mic capture is disabled on LAN HTTP.');
            return;
        }

        this.setState('requesting_mic');

        // 3. Fetch temporary single-use token from backend /token
        let tempToken = null;
        try {
            const headers = {};
            const localToken = window.BridgeClient?.localToken;
            if (localToken) {
                headers['Authorization'] = `Bearer ${localToken}`;
            }

            const response = await fetch('/token', { headers });
            if (!response.ok) {
                const errData = await response.json().catch(() => ({}));
                const serverMsg = errData.detail || errData.message || response.statusText;
                throw new Error(serverMsg || `HTTP ${response.status}`);
            }

            const data = await response.json();
            tempToken = data.token;
            if (!tempToken) {
                throw new Error('Server returned empty streaming token');
            }
        } catch (err) {
            console.warn('[SpeechService] AssemblyAI streaming token fetch failed:', err);
            const SpeechRec = typeof window !== 'undefined' ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null;
            if (SpeechRec) {
                console.log('[SpeechService] Seamlessly activating browser Web Speech recognition fallback...');
                return this.startWebSpeechFallback();
            }
            this.reportError(`Token error: ${err.message || 'Unable to connect to bridge server'}`);
            return;
        }

        // 4. Request microphone access
        try {
            this.mediaStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true
                }
            });
        } catch (err) {
            console.error('[SpeechService] getUserMedia error:', err);
            let userMsg = 'Microphone permission denied or device not found.';
            if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
                userMsg = 'Microphone permission was denied by browser. Please allow microphone access.';
            } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
                userMsg = 'No audio input microphone detected.';
            }
            this.reportError(userMsg);
            return;
        }

        // 5. Initialize Web Audio Context
        try {
            const AudioContextClass = window.AudioContext || window.webkitAudioContext;
            this.audioContext = new AudioContextClass({ sampleRate: 16000 });
        } catch (err) {
            console.error('[SpeechService] AudioContext error:', err);
            this.reportError('Web AudioContext initialization failed.');
            return;
        }

        // Handle AudioContext sample rate fallback (some browsers ignore requested 16 kHz)
        const effectiveSampleRate = this.audioContext.sampleRate || 16000;

        this.lastProcessedTurnOrder = null;

        // 6. Connect to AssemblyAI Streaming WebSocket v3
        const wsParams = new URLSearchParams({
            token: tempToken,
            speech_model: 'universal-3-6-pro',
            sample_rate: effectiveSampleRate.toString(),
            encoding: 'pcm_s16le',
            format_turns: 'true'
        });
        const wsUrl = `wss://streaming.assemblyai.com/v3/ws?${wsParams.toString()}`;

        try {
            this.socket = new WebSocket(wsUrl);
        } catch (err) {
            console.error('[SpeechService] WebSocket creation error:', err);
            this.reportError('Failed to establish AssemblyAI WebSocket connection.');
            return;
        }

        this.socket.binaryType = 'arraybuffer';

        this.socket.onopen = () => {
            if (this.state !== 'requesting_mic') return;
            this.setState('listening');
            this.startAudioCapture();
        };

        this.socket.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                const messageType = message.type || message.message_type;

                if (messageType === 'Turn') {
                    const transcript = (message.transcript || message.text || '').trim();
                    const endOfTurn = Boolean(message.end_of_turn);
                    const turnOrder = message.turn_order;
                    const turnIsFormatted = message.turn_is_formatted;

                    if (endOfTurn) {
                        // When format_turns=true is used, AssemblyAI sends an unformatted turn first
                        // followed immediately by the formatted version for the same turn_order.
                        // Skip the preliminary unformatted turn to avoid processing twice.
                        if (turnIsFormatted === false) {
                            return;
                        }

                        // Deduplicate turns by turn_order so one spoken task never runs twice
                        if (turnOrder !== undefined && turnOrder !== null) {
                            if (this.lastProcessedTurnOrder === turnOrder) {
                                return;
                            }
                            this.lastProcessedTurnOrder = turnOrder;
                        }

                        if (typeof this.onFinal === 'function' && transcript) {
                            this.onFinal(transcript, {
                                turnOrder: turnOrder,
                                turnIsFormatted: turnIsFormatted
                            });
                        }
                    } else {
                        if (typeof this.onPartial === 'function' && transcript) {
                            this.onPartial(transcript, {
                                turnOrder: turnOrder
                            });
                        }
                    }
                } else if (messageType === 'Termination') {
                    // Graceful termination confirmed by AssemblyAI server
                    if (this.terminateResolve) {
                        this.terminateResolve();
                        this.terminateResolve = null;
                    }
                } else if (messageType === 'Error' || message.error) {
                    const errDetail = message.error || message.message || 'AssemblyAI streaming error';
                    console.error('[SpeechService] AssemblyAI error message:', message);
                    this.reportError(errDetail);
                }
            } catch (e) {
                console.error('[SpeechService] Message parsing error:', e, event.data);
            }
        };

        this.socket.onerror = (event) => {
            console.error('[SpeechService] WebSocket error:', event);
            if (this.state === 'listening' || this.state === 'requesting_mic') {
                this.reportError('AssemblyAI streaming WebSocket error.');
            }
        };

        this.socket.onclose = (event) => {
            if (this.state === 'listening' || this.state === 'requesting_mic') {
                this.reportError(`AssemblyAI stream closed (code ${event.code}).`);
            } else if (this.state === 'processing') {
                // If waiting for termination, unblock
                if (this.terminateResolve) {
                    this.terminateResolve();
                    this.terminateResolve = null;
                }
            }
        };
    }

    startAudioCapture() {
        if (!this.audioContext || !this.mediaStream) return;

        // Note: ScriptProcessorNode is deprecated in modern Web Audio specifications in favor of
        // AudioWorkletNode, but is used here for zero-dependency standalone execution in vanilla JS
        // without bundling or external worklet files.
        try {
            const source = this.audioContext.createMediaStreamSource(this.mediaStream);
            this.scriptProcessor = this.audioContext.createScriptProcessor(4096, 1, 1);

            const zeroGain = this.audioContext.createGain();
            zeroGain.gain.value = 0;

            source.connect(this.scriptProcessor);
            this.scriptProcessor.connect(zeroGain);
            zeroGain.connect(this.audioContext.destination);

            this.scriptProcessor.onaudioprocess = (event) => {
                if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return;

                const inputFloat = event.inputBuffer.getChannelData(0);
                const pcm16 = new Int16Array(inputFloat.length);
                for (let i = 0; i < inputFloat.length; i++) {
                    const sample = Math.max(-1, Math.min(1, inputFloat[i]));
                    pcm16[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
                }

                try {
                    this.socket.send(pcm16.buffer);
                } catch (e) {
                    console.error('[SpeechService] Error sending audio chunk:', e);
                }
            };
        } catch (e) {
            console.error('[SpeechService] Error initializing audio processing pipeline:', e);
            this.reportError('Audio capture pipeline failed.');
        }
    }

    async stop() {
        // Guard against stop when not listening or requesting
        if (this.state !== 'listening' && this.state !== 'requesting_mic') {
            return;
        }

        // If still requesting mic and socket is not yet open
        if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
            this.cleanup();
            this.setState('stopped');
            return;
        }

        this.setState('processing');

        // Stop microphone processing immediately to stop capturing new speech
        if (this.scriptProcessor) {
            try {
                this.scriptProcessor.disconnect();
            } catch (e) {}
            this.scriptProcessor.onaudioprocess = null;
            this.scriptProcessor = null;
        }

        // Send Terminate and await server Termination message so last words arrive
        try {
            await new Promise((resolve) => {
                this.terminateResolve = resolve;
                const timeout = setTimeout(() => {
                    if (this.terminateResolve) {
                        this.terminateResolve();
                        this.terminateResolve = null;
                    }
                }, 3000); // 3-second safety timeout

                try {
                    this.socket.send(JSON.stringify({ type: 'Terminate' }));
                } catch (e) {
                    clearTimeout(timeout);
                    resolve();
                }
            });
        } finally {
            this.cleanup();
            this.setState('stopped');
        }
    }

    cleanup() {
        if (this.scriptProcessor) {
            try {
                this.scriptProcessor.disconnect();
            } catch (e) {}
            this.scriptProcessor.onaudioprocess = null;
            this.scriptProcessor = null;
        }

        if (this.mediaStream) {
            try {
                this.mediaStream.getTracks().forEach((track) => track.stop());
            } catch (e) {}
            this.mediaStream = null;
        }

        if (this.audioContext) {
            try {
                if (this.audioContext.state !== 'closed') {
                    this.audioContext.close();
                }
            } catch (e) {}
            this.audioContext = null;
        }

        this.lastProcessedTurnOrder = null;

        if (this.socket) {
            try {
                if (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING) {
                    this.socket.close();
                }
            } catch (e) {}
            this.socket = null;
        }

        if (this.webSpeechRec) {
            try {
                this.webSpeechRec.stop();
            } catch (e) {}
            this.webSpeechRec = null;
        }
    }

    startWebSpeechFallback() {
        const SpeechRec = typeof window !== 'undefined' ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null;
        if (!SpeechRec) {
            this.reportError('Speech recognition is not supported in this browser.');
            return;
        }
        try {
            this.webSpeechRec = new SpeechRec();
            this.webSpeechRec.continuous = true;
            this.webSpeechRec.interimResults = true;
            this.webSpeechRec.lang = 'en-US';

            this.webSpeechRec.onstart = () => {
                this.setState('listening');
            };

            this.webSpeechRec.onresult = (event) => {
                let interim = '';
                let final = '';
                for (let i = event.resultIndex; i < event.results.length; ++i) {
                    if (event.results[i].isFinal) {
                        final += event.results[i][0].transcript;
                    } else {
                        interim += event.results[i][0].transcript;
                    }
                }
                if (interim && typeof this.onPartial === 'function') {
                    this.onPartial(interim.trim());
                }
                if (final && typeof this.onFinal === 'function') {
                    this.onFinal(final.trim());
                }
            };

            this.webSpeechRec.onerror = (e) => {
                if (e.error !== 'no-speech') {
                    console.error('[SpeechService] WebSpeech error:', e);
                }
            };

            this.webSpeechRec.onend = () => {
                if (this.state === 'listening') {
                    this.setState('stopped');
                }
            };

            this.webSpeechRec.start();
        } catch (err) {
            console.error('[SpeechService] Failed to start Web Speech recognition:', err);
            this.reportError('Failed to start microphone speech recognition.');
        }
    }
}

// Expose SpeechService instance on window
window.SpeechService = new SpeechService();
