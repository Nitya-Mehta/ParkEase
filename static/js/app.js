document.addEventListener('DOMContentLoaded', () => {
    const countdownNodes = document.querySelectorAll('[data-countdown-end]');
    const formatCountdown = (targetIso) => {
        const target = new Date(targetIso);
        const diffMs = target.getTime() - Date.now();
        if (Number.isNaN(target.getTime())) {
            return 'Schedule unavailable';
        }
        if (diffMs <= 0) {
            const overMinutes = Math.floor(Math.abs(diffMs) / 60000);
            return `Overdue by ${overMinutes} min`;
        }
        const totalMinutes = Math.floor(diffMs / 60000);
        const hours = Math.floor(totalMinutes / 60);
        const minutes = totalMinutes % 60;
        return `${hours}h ${minutes}m left`;
    };

    if (countdownNodes.length) {
        const updateCountdowns = () => {
            countdownNodes.forEach((node) => {
                node.textContent = formatCountdown(node.dataset.countdownEnd);
            });
        };
        updateCountdowns();
        window.setInterval(updateCountdowns, 60000);
    }

    const flashMessages = document.querySelectorAll('.messages .alert');
    flashMessages.forEach((alert, index) => {
        window.setTimeout(() => {
            alert.classList.add('is-dismissing');
            window.setTimeout(() => {
                alert.remove();
                const container = document.querySelector('.messages');
                if (container && !container.children.length) {
                    container.remove();
                }
            }, 260);
        }, 3200 + (index * 250));
    });

    const mobileBtn = document.getElementById('mobileMenuBtn');
    const navbar = document.querySelector('.navbar');

    if (mobileBtn && navbar) {
        mobileBtn.addEventListener('click', () => {
            navbar.classList.toggle('nav-open');
        });
    }

    const preserveLinks = document.querySelectorAll('[data-preserve-scroll]');
    preserveLinks.forEach((link) => {
        link.addEventListener('click', () => {
            const target = link.getAttribute('data-preserve-scroll');
            const anchor = document.getElementById(target);
            sessionStorage.setItem('pe:scroll-path', window.location.pathname + window.location.search);
            sessionStorage.setItem('pe:scroll-y', String(window.scrollY));
            if (anchor) {
                sessionStorage.setItem('pe:scroll-anchor', target);
            }
        });
    });

    document.addEventListener('click', (event) => {
        const link = event.target.closest('[data-preserve-scroll]');
        if (!link) {
            return;
        }
        const target = link.getAttribute('data-preserve-scroll');
        const anchor = document.getElementById(target);
        sessionStorage.setItem('pe:scroll-path', window.location.pathname + window.location.search);
        sessionStorage.setItem('pe:scroll-y', String(window.scrollY));
        if (anchor) {
            sessionStorage.setItem('pe:scroll-anchor', target);
        }
    });

    const scrollPath = sessionStorage.getItem('pe:scroll-path');
    const scrollY = sessionStorage.getItem('pe:scroll-y');
    const scrollAnchor = sessionStorage.getItem('pe:scroll-anchor');
    if (scrollPath === window.location.pathname + window.location.search && scrollY) {
        window.requestAnimationFrame(() => {
            if (scrollAnchor) {
                const anchor = document.getElementById(scrollAnchor);
                if (anchor) {
                    const anchorTop = anchor.getBoundingClientRect().top + window.scrollY - 96;
                    window.scrollTo({ top: Math.max(anchorTop, Number(scrollY)), behavior: 'auto' });
                } else {
                    window.scrollTo({ top: Number(scrollY), behavior: 'auto' });
                }
            } else {
                window.scrollTo({ top: Number(scrollY), behavior: 'auto' });
            }
            sessionStorage.removeItem('pe:scroll-path');
            sessionStorage.removeItem('pe:scroll-y');
            sessionStorage.removeItem('pe:scroll-anchor');
        });
    }

    const applyLiveSlotState = (container, slotData) => {
        let slotNode = container.querySelector(`[data-slot-id="${slotData.id}"]`);
        if (!slotNode) {
            return;
        }

        let bayNode = slotNode.classList.contains('parking-bay') ? slotNode : slotNode.closest('.parking-bay');
        if (!bayNode) {
            return;
        }

        const isOwned = container.dataset.ownedSlotId === String(slotData.id);
        const isRequested = container.dataset.requestedSlotId === String(slotData.id);
        const isAssigned = slotData.status === 'Assigned';
        const isDisabled = !slotData.is_active;
        const isBookingBoard = Boolean(bayNode.closest('#bookingExperience'));

        if (isBookingBoard && !isDisabled && !isAssigned && bayNode.tagName === 'DIV' && bayNode.dataset.confirmUrl) {
            const anchor = document.createElement('a');
            anchor.className = bayNode.className;
            anchor.innerHTML = bayNode.innerHTML;
            anchor.dataset.slotId = bayNode.dataset.slotId;
            anchor.dataset.confirmUrl = bayNode.dataset.confirmUrl;
            anchor.href = bayNode.dataset.confirmUrl;
            anchor.setAttribute('data-preserve-scroll', 'bookingExperience');
            bayNode.replaceWith(anchor);
            bayNode = anchor;
        }

        bayNode.classList.remove('free', 'occupied', 'bay-disabled');
        if (isDisabled) {
            bayNode.classList.add('occupied', 'bay-disabled');
        } else if (isAssigned) {
            bayNode.classList.add('occupied');
        } else {
            bayNode.classList.add('free');
        }

        const statusNode = bayNode.querySelector('.bay-status');
        if (statusNode) {
            if (isDisabled) {
                statusNode.textContent = 'Disabled';
            } else if (isOwned) {
                statusNode.textContent = 'Your Spot';
            } else if (isRequested) {
                statusNode.textContent = 'Requested';
            } else if (isAssigned) {
                statusNode.textContent = 'Occupied';
            } else {
                statusNode.textContent = isBookingBoard ? 'Free' : 'Available';
            }
        }

        if (bayNode.matches('a, div') && bayNode.hasAttribute('data-confirm-url')) {
            if (!isDisabled && !isAssigned && bayNode.tagName === 'A') {
                bayNode.href = bayNode.dataset.confirmUrl;
                bayNode.removeAttribute('aria-disabled');
                bayNode.style.pointerEvents = '';
                bayNode.style.opacity = '';
            } else {
                if (bayNode.tagName === 'A') {
                    bayNode.removeAttribute('href');
                }
                bayNode.setAttribute('aria-disabled', 'true');
                bayNode.style.pointerEvents = 'none';
                bayNode.style.opacity = '0.92';
            }
        }
    };

    const refreshLiveSummaries = (container, summaries) => {
        const activeAreaButton = container.querySelector('[data-area-target].active');
        const activeArea = activeAreaButton ? activeAreaButton.dataset.areaTarget : container.dataset.defaultArea;
        container.querySelectorAll('[data-level-target]').forEach((button) => {
            const freeLabel = button.querySelector('[data-free-label]');
            if (!freeLabel) {
                return;
            }
            const summaryKey = `${activeArea}:${button.dataset.levelTarget}`;
            if (summaryKey in summaries) {
                freeLabel.textContent = `${summaries[summaryKey]} free`;
            }
        });
    };

    const liveContainers = document.querySelectorAll('[data-live-slots]');
    liveContainers.forEach((container) => {
        const liveUrl = container.dataset.liveUrl;
        if (!liveUrl) {
            return;
        }

        const refreshSlots = async () => {
            try {
                const response = await fetch(liveUrl, {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                });
                if (!response.ok) {
                    return;
                }
                const payload = await response.json();
                payload.slots.forEach((slotData) => applyLiveSlotState(container, slotData));
                refreshLiveSummaries(container, payload.summaries || {});
            } catch (error) {
                // Keep polling silent to avoid interrupting the booking/dashboard flow.
            }
        };

        refreshSlots();
        window.setInterval(refreshSlots, 8000);
    });

    const switchers = document.querySelectorAll('[data-switcher]');
    switchers.forEach((switcher) => {
        const areaButtons = Array.from(switcher.querySelectorAll('[data-area-target]'));
        const levelButtons = Array.from(switcher.querySelectorAll('[data-level-target]'));
        const panels = Array.from(switcher.querySelectorAll('[data-area-panel][data-level-panel]'));
        const bookingLinks = Array.from(switcher.querySelectorAll('[data-booking-link]'));
        const title = switcher.querySelector('#bookingSelectionTitle, #adminSlotsTitle');
        const fallbackHeading = switcher.querySelector('.layout-board-head h3, .slot-list-head h3');
        const titleTarget = title || fallbackHeading;
        const caption = switcher.querySelector('#bookingSelectionCaption');

        let activeArea = switcher.dataset.defaultArea;
        let activeLevel = switcher.dataset.defaultLevel;

        const sync = () => {
            areaButtons.forEach((button) => {
                button.classList.toggle('active', button.dataset.areaTarget === activeArea);
            });

            levelButtons.forEach((button) => {
                button.classList.toggle('active', button.dataset.levelTarget === activeLevel);
                const freeLabel = button.querySelector('[data-free-label]');
                const freeCounts = button.dataset.freeCounts;
                if (freeLabel && freeCounts) {
                    const activeCount = freeCounts
                        .split('|')
                        .map((entry) => entry.split(':'))
                        .find(([area]) => area === activeArea);
                    if (activeCount) {
                        freeLabel.textContent = `${activeCount[1]} free`;
                    }
                }
            });

            const activePanel = panels.find((panel) =>
                panel.dataset.areaPanel === activeArea && panel.dataset.levelPanel === activeLevel
            );

            panels.forEach((panel) => {
                const isActive = panel.dataset.areaPanel === activeArea && panel.dataset.levelPanel === activeLevel;
                panel.classList.toggle('active', isActive);
            });

            if (activePanel && titleTarget) {
                titleTarget.textContent = `${activeArea} • ${activePanel.dataset.levelLabel}`;
            }

            if (activePanel && caption && switcher.id === 'bookingExperience') {
                caption.textContent = 'Select any free spot below to continue to the confirmation page.';
            }

            bookingLinks.forEach((link) => {
                const url = new URL(link.href, window.location.origin);
                url.searchParams.set('area', activeArea);
                url.searchParams.set('level', activeLevel);
                link.href = url.pathname + url.search;
            });
        };

        areaButtons.forEach((button) => {
            button.addEventListener('click', () => {
                activeArea = button.dataset.areaTarget;
                sync();
                const scrollTarget = button.dataset.scrollTarget;
                if (scrollTarget) {
                    const target = document.getElementById(scrollTarget);
                    if (target) {
                        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }
                }
            });
        });

        levelButtons.forEach((button) => {
            button.addEventListener('click', () => {
                activeLevel = button.dataset.levelTarget;
                sync();
            });
        });

        sync();
    });

    const scanForm = document.getElementById('vehicleScanForm');
    if (scanForm) {
        const video = document.getElementById('scanCameraFeed');
        const canvas = document.getElementById('scanCaptureCanvas');
        const fallback = document.getElementById('scanCameraFallback');
        const startButton = document.getElementById('scanStartCamera');
        const captureButton = document.getElementById('scanCaptureFrame');
        const resetButton = document.getElementById('scanResetCapture');
        const imageInput = scanForm.querySelector('input[type="file"][name="image"]');
        const capturedInput = scanForm.querySelector('[name="captured_image_data"]');
        let activeStream = null;

        const stopStream = () => {
            if (!activeStream) {
                return;
            }
            activeStream.getTracks().forEach((track) => track.stop());
            activeStream = null;
        };

        const setFallback = (message) => {
            if (fallback) {
                fallback.textContent = message;
                fallback.hidden = false;
            }
        };

        const isMobileDevice = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent || '');
        const canUseBrowserCamera = Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);

        if (startButton) {
            startButton.addEventListener('click', async () => {
                if (!canUseBrowserCamera) {
                    setFallback('This browser does not support live camera preview here. Use the upload field to open the rear camera.');
                    if (imageInput) {
                        imageInput.click();
                    }
                    return;
                }

                if (!window.isSecureContext && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
                    setFallback('Live camera needs HTTPS on mobile browsers. Use the upload field below to open the rear camera instead.');
                    if (imageInput) {
                        imageInput.click();
                    }
                    return;
                }

                try {
                    stopStream();
                    const preferredConstraints = isMobileDevice
                        ? {
                            video: {
                                facingMode: { ideal: 'environment' },
                                width: { ideal: 1920 },
                                height: { ideal: 1080 },
                            },
                            audio: false,
                        }
                        : {
                            video: {
                                facingMode: 'environment',
                            },
                            audio: false,
                        };
                    activeStream = await navigator.mediaDevices.getUserMedia(preferredConstraints);
                    video.srcObject = activeStream;
                    video.hidden = false;
                    canvas.hidden = true;
                    if (fallback) {
                        fallback.hidden = true;
                    }
                } catch (error) {
                    try {
                        stopStream();
                        activeStream = await navigator.mediaDevices.getUserMedia({
                            video: {
                                facingMode: { exact: 'environment' },
                            },
                            audio: false,
                        });
                        video.srcObject = activeStream;
                        video.hidden = false;
                        canvas.hidden = true;
                        if (fallback) {
                            fallback.hidden = true;
                        }
                    } catch (retryError) {
                        setFallback('Live rear camera could not open here. Use the upload field below to open the phone rear camera.');
                        if (imageInput && isMobileDevice) {
                            imageInput.click();
                        }
                    }
                }
            });
        }

        if (imageInput) {
            imageInput.addEventListener('change', () => {
                if (capturedInput && imageInput.files && imageInput.files.length) {
                    capturedInput.value = '';
                }
            });
        }

        if (captureButton) {
            captureButton.addEventListener('click', () => {
                if (!video || !canvas || !capturedInput || !video.videoWidth) {
                    setFallback('Start the camera first, then capture a frame.');
                    return;
                }
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                const context = canvas.getContext('2d');
                context.drawImage(video, 0, 0, canvas.width, canvas.height);
                capturedInput.value = canvas.toDataURL('image/jpeg', 0.92);
                canvas.hidden = false;
                video.hidden = true;
                setFallback('Frame captured. Submit to run verification or reset to retake.');
                stopStream();
            });
        }

        if (resetButton) {
            resetButton.addEventListener('click', () => {
                if (capturedInput) {
                    capturedInput.value = '';
                }
                if (canvas) {
                    canvas.hidden = true;
                }
                if (video) {
                    video.hidden = false;
                }
                setFallback('Capture reset. Start the camera again or upload an image.');
            });
        }

        window.addEventListener('beforeunload', stopStream);
    }

    const chatbotForm = document.getElementById('chatbotForm');
    if (chatbotForm) {
        const input = document.getElementById('chatbotInput');
        const messages = document.getElementById('chatbotMessages');
        const csrfInput = chatbotForm.querySelector('[name=csrfmiddlewaretoken]');

        const addMessage = (text, type) => {
            const bubble = document.createElement('div');
            bubble.className = `chatbot-message ${type}`;
            bubble.textContent = text;
            messages.appendChild(bubble);
            messages.scrollTop = messages.scrollHeight;
        };

        const askBot = async (message) => {
            addMessage(message, 'user');
            input.value = '';
            input.disabled = true;

            const formData = new FormData();
            formData.append('message', message);

            try {
                const response = await fetch(chatbotForm.dataset.chatbotUrl, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfInput.value },
                    body: formData,
                });
                const data = await response.json();
                addMessage(data.reply || 'I could not answer that right now.', 'bot');
            } catch (error) {
                addMessage('Chatbot is unavailable right now. Please try again.', 'bot');
            } finally {
                input.disabled = false;
                input.focus();
            }
        };

        chatbotForm.addEventListener('submit', (event) => {
            event.preventDefault();
            const message = input.value.trim();
            if (message) {
                askBot(message);
            }
        });

        document.querySelectorAll('[data-chat-suggestion]').forEach((button) => {
            button.addEventListener('click', () => askBot(button.dataset.chatSuggestion));
        });
    }
});
