'''DICOM 上传转换的回归测试'''

from __future__ import annotations

from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import nibabel as nib
import numpy as np
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid

from services.dicom_conversion import (
    _convert_dicom_series,
    _modality_from_dicom_description,
    _select_dicom_series,
    DICOMSeriesSelectionRequired,
    initialize_uploaded_dicom_task,
)


class DicomConversionTests(unittest.TestCase):
    '''验证四序列 DICOM 的识别、转换与临时文件清理'''

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.dicom_dir = self.root / "dicom"
        self.dicom_dir.mkdir()
        self.paths = self._create_case()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _create_case(self) -> list[Path]:
        study_uid = generate_uid()
        descriptions = {
            "flair": "AX T2 FLAIR",
            "t1ce": "AX T1 POST CONTRAST",
            "t1": "AX T1 PRE",
            "t2": "AX T2",
        }
        paths: list[Path] = []
        for modality, description in descriptions.items():
            series_uid = generate_uid()
            for index in range(3):
                path = self.dicom_dir / f"{modality}-{index}.dcm"
                self._write_dicom(
                    path,
                    study_uid=study_uid,
                    series_uid=series_uid,
                    description=description,
                    instance_number=index + 1,
                    pixel_value=(index + 1) * 10,
                )
                paths.append(path)
        return paths

    def _write_dicom(
        self,
        path: Path,
        *,
        study_uid: str,
        series_uid: str,
        description: str,
        instance_number: int,
        pixel_value: int,
    ) -> None:
        file_meta = Dataset()
        file_meta.MediaStorageSOPClassUID = MRImageStorage
        file_meta.MediaStorageSOPInstanceUID = generate_uid()
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        dataset = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
        dataset.SOPClassUID = MRImageStorage
        dataset.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
        dataset.StudyInstanceUID = study_uid
        dataset.SeriesInstanceUID = series_uid
        dataset.SeriesDescription = description
        dataset.ProtocolName = description
        dataset.Modality = "MR"
        dataset.PatientName = "Test^Case"
        dataset.PatientID = "test"
        dataset.Rows = 4
        dataset.Columns = 4
        dataset.SamplesPerPixel = 1
        dataset.PhotometricInterpretation = "MONOCHROME2"
        dataset.BitsAllocated = 16
        dataset.BitsStored = 16
        dataset.HighBit = 15
        dataset.PixelRepresentation = 0
        dataset.PixelSpacing = [1, 1]
        dataset.SliceThickness = 1
        dataset.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        dataset.ImagePositionPatient = [0, 0, instance_number - 1]
        dataset.InstanceNumber = instance_number
        dataset.PixelData = np.full((4, 4), pixel_value, dtype=np.uint16).tobytes()
        dataset.save_as(path, enforce_file_format=True)

    def test_dicom_series_are_recognized_and_converted_to_a_shared_grid(self) -> None:
        selected = _select_dicom_series(self.paths)
        converted = _convert_dicom_series(
            self.dicom_dir,
            self.root / "converted",
            selected,
        )

        images = {modality: nib.load(path) for modality, path in converted.items()}
        self.assertEqual(set(images), {"flair", "t1ce", "t1", "t2"})
        self.assertEqual(images["flair"].shape, (4, 4, 3))
        for modality in ("t1ce", "t1", "t2"):
            self.assertEqual(images[modality].shape, images["flair"].shape)
            self.assertTrue(np.allclose(images[modality].affine, images["flair"].affine))

    def test_uploaded_dicom_is_stored_as_nifti_without_retaining_raw_files(self) -> None:
        task_dir = self.root / "task"
        task_dir.mkdir()
        repository = Mock()
        with ExitStack() as streams, patch("services.task_files.task_repository", repository):
            stored = initialize_uploaded_dicom_task(
                task_dir,
                [
                    (path.name, streams.enter_context(path.open("rb")))
                    for path in self.paths
                ],
                name="dicom test",
            )

        self.assertEqual(set(stored), {"flair", "t1ce", "t1", "t2"})
        self.assertTrue(all(path.is_file() for path in stored.values()))
        self.assertFalse((task_dir / ".dicom-staging").exists())
        self.assertFalse((task_dir / ".dicom-converted").exists())
        saved_record = repository.save.call_args.args[1]
        self.assertEqual(saved_record.input.modalities["flair"].original_filename, "flair_from_dicom.nii.gz")

    def test_missing_dicom_modality_has_a_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "未识别到 T2 DICOM 序列"):
            _select_dicom_series(
                [path for path in self.paths if not path.name.startswith("t2-")]
            )

    def test_t1_contrast_suffix_is_recognized(self) -> None:
        self.assertEqual(
            _modality_from_dicom_description("T1/3D/FFE/C"),
            "t1ce",
        )

    def test_duplicate_series_can_be_selected_by_user_choice(self) -> None:
        duplicate_path = self.dicom_dir / "t1-extra.dcm"
        self._write_dicom(
            duplicate_path,
            study_uid=generate_uid(),
            series_uid=generate_uid(),
            description="AX T1 PRE",
            instance_number=1,
            pixel_value=1,
        )

        with self.assertRaises(DICOMSeriesSelectionRequired) as caught:
            _select_dicom_series([*self.paths, duplicate_path])

        candidates = caught.exception.modalities["t1"]
        selected = _select_dicom_series(
            [*self.paths, duplicate_path],
            {"t1": candidates[0]["series_uid"]},
        )
        self.assertEqual(selected["t1"], candidates[0]["series_uid"])


if __name__ == "__main__":
    unittest.main()
