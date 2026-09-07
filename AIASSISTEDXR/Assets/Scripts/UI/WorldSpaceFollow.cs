using UnityEngine;

namespace NeuroGuideXR.UI
{
    /// <summary>
    /// Makes this GameObject smoothly follow the AR camera.
    /// Attach to any world-space panel that should stay in view.
    /// </summary>
    public sealed class WorldSpaceFollow : MonoBehaviour
    {
        [Header("Follow Settings")]
        [SerializeField] private float followDistance = 1.6f;
        [SerializeField] private float verticalOffset  = -0.18f;  // slightly below centre
        [SerializeField] private float smoothTime      = 0.22f;   // lerp speed
        [SerializeField] private float snapDistance    = 2.0f;    // snap if drifted too far

        private Camera   _cam;
        private Vector3  _velPos = Vector3.zero;
        private Vector3  _velRot = Vector3.zero;  // unused — using Slerp for rotation

        private void Start()
        {
            _cam = Camera.main;
            if (_cam == null)
                _cam = FindFirstObjectByType<Camera>();

            // Snap to initial position immediately
            if (_cam != null) SnapToCamera();
        }

        private void LateUpdate()
        {
            if (_cam == null) return;

            Vector3 targetPos = _cam.transform.position
                              + _cam.transform.forward * followDistance
                              + _cam.transform.up      * verticalOffset;

            // Snap immediately if panel has drifted too far
            float dist = Vector3.Distance(transform.position, targetPos);
            if (dist > snapDistance)
            {
                transform.position = targetPos;
            }
            else
            {
                transform.position = Vector3.SmoothDamp(
                    transform.position, targetPos, ref _velPos, smoothTime);
            }

            // Smoothly face the camera (billboard)
            // Adjust rotation to fix the upside-down text issue
            Vector3 directionToCamera = transform.position - _cam.transform.position;
            Quaternion targetRot = Quaternion.LookRotation(
                directionToCamera, _cam.transform.up);
    
            // Ensure the UI is always upright
            transform.rotation = Quaternion.Slerp(
                transform.rotation, targetRot, Time.deltaTime / smoothTime);
        }

        public void SnapToCamera()
        {
            if (_cam == null) return;
            transform.position = _cam.transform.position
                               + _cam.transform.forward * followDistance
                               + _cam.transform.up      * verticalOffset;
            transform.rotation = Quaternion.LookRotation(
                transform.position - _cam.transform.position);
        }
    }
}
