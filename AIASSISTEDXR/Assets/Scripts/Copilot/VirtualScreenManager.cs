// Assets/Scripts/Copilot/VirtualScreenManager.cs
// =================================================
// Places an AR Quad ("virtual screen") in the real world, directly in front
// of the user's camera. Streams the live PC screen as a JPEG texture.
//
// FIXES vs the old version:
//   • PlaceScreenForward() now runs as a coroutine so it waits for Camera.main
//     to be valid (ARCore may take a frame or two to initialise).
//   • Texture decode is deferred to end-of-frame to prevent mid-frame GPU tears.
//   • ARCore camera rotation is respected: the Quad always faces the camera, not
//     just at placement time (optional — controlled by TrackCamera).
//   • ResetPlacement() clears the old position first to avoid flicker.
//   • ApplyScreenFrame() is safe to call every frame (debounced by dirty flag).

using System;
using System.Collections;
using UnityEngine;

namespace NeuroGuideXR.Copilot
{
    public sealed class VirtualScreenManager : MonoBehaviour
    {
        // ----------------------------------------------------------------
        // Inspector
        // ----------------------------------------------------------------
        [Header("Virtual Screen")]
        [Tooltip("The Quad GameObject that represents the PC monitor in AR.")]
        [SerializeField] private GameObject virtualScreen;

        [Tooltip("Renderer on the Quad.")]
        [SerializeField] private Renderer screenRenderer;

        [Tooltip("Unlit/Texture material assigned explicitly to bypass Android shader stripping.")]
        [SerializeField] public Material screenMaterial;

        [Tooltip("Distance in metres to place the screen in front of the camera.")]
        [SerializeField] private float placementDistance = 1.2f;

        [Tooltip("If true, the Quad rotates every frame to stay facing the camera. " +
                 "Useful when the user moves their head. Disable if the screen flickers.")]
        [SerializeField] private bool trackCamera = false;

        [Tooltip("Seconds to wait after Start before auto-placing. " +
                 "Increase if ARCore takes a while to stabilise camera pose.")]
        [SerializeField] private float placementDelay = 1.2f;

        // ----------------------------------------------------------------
        // Runtime state
        // ----------------------------------------------------------------
        private bool      _placed;
        private Texture2D _screenTexture;
        private bool      _textureDirty;
        private byte[]    _pendingBytes;
        private bool      _warnedMissingRenderer;

        // Coroutine handles for safe stop
        private Coroutine _placeCoroutine;
        private Coroutine _frameCoroutine;

        public bool IsPlaced => _placed;

        // ----------------------------------------------------------------
        // Lifecycle
        // ----------------------------------------------------------------
        private void Awake()
        {
            ResolveReferences();
            if (virtualScreen != null)
                virtualScreen.SetActive(false);
        }

        private void Start()
        {
            _placeCoroutine = StartCoroutine(PlaceAfterDelay(placementDelay));
        }

        private void Update()
        {
            // If tracking: smoothly rotate Quad to always face the camera
            if (trackCamera && _placed && virtualScreen != null)
            {
                var cam = Camera.main;
                if (cam != null)
                {
                    Quaternion target = Quaternion.LookRotation(
                        virtualScreen.transform.position - cam.transform.position);
                    virtualScreen.transform.rotation = Quaternion.Slerp(
                        virtualScreen.transform.rotation, target, Time.deltaTime * 8f);
                }
            }
        }

        private void LateUpdate()
        {
            // Apply pending texture at LateUpdate (end of frame) to avoid GPU tears
            if (_textureDirty && _pendingBytes != null)
            {
                ApplyBytesNow(_pendingBytes);
                _textureDirty = false;
                _pendingBytes = null;
            }
        }

        private void OnDestroy()
        {
            if (_screenTexture != null)
                Destroy(_screenTexture);
        }

        // ----------------------------------------------------------------
        // Placement
        // ----------------------------------------------------------------

        /// <summary>
        /// Coroutine: waits for Camera.main to be valid, then places the screen.
        /// Retries every frame until the camera is available (ARCore-safe).
        /// </summary>
        private IEnumerator PlaceAfterDelay(float delay)
        {
            // Wait for the requested delay
            yield return new WaitForSeconds(delay);

            // Wait until Camera.main is available (ARCore may not have it yet)
            float waited = 0f;
            while (Camera.main == null && waited < 10f)
            {
                yield return null;
                waited += Time.deltaTime;
            }

            if (Camera.main == null)
            {
                Debug.LogWarning("[VirtualScreen] Camera.main never became available — cannot place screen.");
                yield break;
            }

            PlaceScreenForward();
        }

        /// <summary>Immediately place the virtual screen in front of the camera.</summary>
        public void PlaceScreenForward()
        {
            if (virtualScreen == null) return;

            var cam = Camera.main;
            if (cam == null)
            {
                // Re-try via coroutine
                if (_placeCoroutine != null) StopCoroutine(_placeCoroutine);
                _placeCoroutine = StartCoroutine(PlaceAfterDelay(0.5f));
                return;
            }

            // Disable first to avoid one-frame flash at wrong position
            virtualScreen.SetActive(false);

            virtualScreen.transform.position = cam.transform.position
                                             + cam.transform.forward * placementDistance;
            virtualScreen.transform.rotation = Quaternion.LookRotation(
                virtualScreen.transform.position - cam.transform.position);

            virtualScreen.SetActive(true);
            _placed = true;

            Debug.Log($"[VirtualScreen] Placed at {virtualScreen.transform.position} " +
                      $"(distance={placementDistance:F2}m)");
        }

        /// <summary>Re-place the virtual screen (e.g. user tapped a reset button).</summary>
        public void ResetPlacement()
        {
            _placed = false;
            if (virtualScreen != null)
                virtualScreen.SetActive(false);

            if (_placeCoroutine != null) StopCoroutine(_placeCoroutine);
            _placeCoroutine = StartCoroutine(PlaceAfterDelay(0.1f));
        }

        // ----------------------------------------------------------------
        // Screen Texture
        // ----------------------------------------------------------------

        /// <summary>
        /// Queue a new JPEG frame for the virtual screen texture.
        /// Safe to call every frame from the WebSocket receive thread or Update().
        /// The actual texture upload happens in LateUpdate() to avoid GPU tears.
        /// </summary>
        public void ApplyScreenFrame(byte[] bytes)
        {
            if (bytes == null || bytes.Length == 0) return;

            // Buffer the latest bytes — older frames that haven't rendered yet are dropped
            _pendingBytes = bytes;
            _textureDirty = true;

            // Ensure the screen is placed when the first frame arrives
            if (!_placed)
                PlaceScreenForward();
        }

        private void ApplyBytesNow(byte[] bytes)
        {
            ResolveReferences();

            if (screenRenderer == null)
            {
                if (!_warnedMissingRenderer)
                {
                    Debug.LogWarning("[VirtualScreen] No Renderer. Assign screenRenderer in Inspector " +
                                     "or ensure virtualScreen has a Renderer component.");
                    _warnedMissingRenderer = true;
                }
                return;
            }

            try
            {
                if (_screenTexture == null)
                {
                    // Start with a sensible default size — LoadImage() will resize automatically
                    _screenTexture = new Texture2D(960, 540, TextureFormat.RGB24, false);

                    // Assign material — prefer the explicitly assigned one (avoids Android shader strip)
                    if (screenMaterial != null)
                    {
                        screenRenderer.material = screenMaterial;
                    }
                    else
                    {
                        // Dynamic shader lookup — only reliable in Editor
                        var unlit = Shader.Find("Universal Render Pipeline/Unlit") ?? 
                                    Shader.Find("Universal Render Pipeline/Simple Lit") ?? 
                                    Shader.Find("Unlit/Texture");
                        if (unlit != null)
                            screenRenderer.material.shader = unlit;
                        else
                            Debug.LogWarning("[VirtualScreen] Compatible shader not found — " +
                                             "assign screenMaterial explicitly in Inspector.");
                    }
                }

                // LoadImage re-uses the existing texture object (no GC allocation)
                bool loaded = _screenTexture.LoadImage(bytes);
                if (loaded)
                {
                    var mat = screenRenderer.material;
                    mat.mainTexture = _screenTexture;
                    if (mat.HasProperty("_BaseMap"))
                    {
                        mat.SetTexture("_BaseMap", _screenTexture);
                    }
                    else
                    {
                        Debug.LogWarning($"[VirtualScreen] Material '{mat.name}' does not have '_BaseMap'. Shader is '{mat.shader.name}'");
                    }
                    Debug.Log($"[VirtualScreen] Texture applied: {bytes.Length} bytes, size={_screenTexture.width}x{_screenTexture.height}, shader={mat.shader.name}");
                }
                else
                {
                    Debug.LogWarning($"[VirtualScreen] LoadImage failed for {bytes.Length} bytes.");
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[VirtualScreen] Texture decode error: {e.Message}");
            }
        }

        // ----------------------------------------------------------------
        // Internal helpers
        // ----------------------------------------------------------------

        private void ResolveReferences()
        {
            if (virtualScreen == null) return;

            if (screenRenderer == null)
            {
                screenRenderer = virtualScreen.GetComponent<Renderer>();
                if (screenRenderer == null)
                    screenRenderer = virtualScreen.GetComponentInChildren<Renderer>(true);
            }

            if (screenMaterial == null && screenRenderer != null)
                screenMaterial = screenRenderer.sharedMaterial;
        }
    }
}
