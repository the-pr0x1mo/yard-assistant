// HTTP success alone does not mean a normalized inspection was saved.
window.describeVoiceResult = function (data) {
  if (data.status === 'completed' && data.normalization_status === 'completed') {
    return {message: `Inspection saved from log #${data.id}. Review the extracted facts before confirming.`, type: 'success'};
  }
  return {message: `Transcript saved as log #${data.id}. ${data.error?.message || 'Processing is incomplete.'} Open Transcripts to review or reprocess.`, type: 'error'};
};
