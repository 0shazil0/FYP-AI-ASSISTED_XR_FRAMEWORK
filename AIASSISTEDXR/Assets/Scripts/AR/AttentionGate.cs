using UnityEngine;

namespace NeuroGuideXR.AR
{
    [RequireComponent(typeof(ARCameraCapture))]
    public sealed class AttentionGate : MonoBehaviour
    {
        [SerializeField] private float accelerationThreshold = 0.12f;
        [SerializeField] private float angularVelocityThreshold = 0.15f;
        [SerializeField] private float fixationDurationSeconds = 0.85f;
        [SerializeField] private float cooldownSeconds = 1.5f;

        private ARCameraCapture _capture;
        private float _stableTime;
        private float _cooldownRemaining;

        private void Awake()
        {
            _capture = GetComponent<ARCameraCapture>();
            Input.gyro.enabled = true;
        }

        private void Update()
        {
            if (_cooldownRemaining > 0f)
            {
                _cooldownRemaining -= Time.deltaTime;
                return;
            }

            Vector3 accel = Input.acceleration;
            Vector3 gyro = Input.gyro.rotationRateUnbiased;

            bool stable = accel.magnitude < accelerationThreshold && gyro.magnitude < angularVelocityThreshold;
            if (!stable)
            {
                _stableTime = 0f;
                return;
            }

            _stableTime += Time.deltaTime;
            if (_stableTime >= fixationDurationSeconds)
            {
                _stableTime = 0f;
                _cooldownRemaining = cooldownSeconds;
                StartCoroutine(_capture.CaptureAndSendFrame());
            }
        }
    }
}
