// Compatibility helper for callers that describe upload responses.
window.describeVoiceResult = function (data) {
  if (data.status === 'review') {
    return {message: 'Kartica je pripremljena. Proverite podatke i potvrdite čuvanje.', type: 'info'};
  }
  if (data.confirmation_status === 'confirmed') {
    return {message: `Pregled #${data.inspection_id} je potvrđen.`, type: 'success'};
  }
  return {message: data.error?.message || 'Pregled nije potvrđen.', type: 'error'};
};
